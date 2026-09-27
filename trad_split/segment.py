"""Turn per-frame music/chat scores into clean set and chat segments.

Pure numpy, no model, so everything here can be tested with synthetic scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SET = "set"
CHAT = "chat"


@dataclass
class Mark:
    """A tune change inside a set. A name ending in "?" marks a guess."""
    time: float  # seconds from the start of the recording
    name: str


@dataclass
class Segment:
    start: float  # seconds
    end: float  # seconds
    kind: str  # SET or CHAT
    name: str = ""
    marks: list[Mark] = field(default_factory=list)  # tune changes, sets only

    @property
    def duration(self) -> float:
        return self.end - self.start

    def tunes(self) -> list[tuple[float, float, str]]:
        """(start, end, name) of each tune in the set, in recording time.

        The first tune starts with the set; each mark starts the next one.
        A mark within 2 s of the set's start just names the first tune.
        """
        first = "Tune 1"
        inner = []
        for m in sorted(self.marks, key=lambda m: m.time):
            if abs(m.time - self.start) <= 2:
                first = m.name
            elif self.start < m.time < self.end:
                inner.append(m)
        starts = [self.start] + [m.time for m in inner]
        ends = starts[1:] + [self.end]
        return list(zip(starts, ends, [first] + [m.name for m in inner]))


@dataclass
class SegmentParams:
    min_set: float = 40.0  # a set shorter than this is folded into the chat around it
    min_chat: float = 4.0  # a gap shorter than this is folded into the sets around it
    pad_start: float = 1.5  # extend each set this far back into the chat before it
    pad_end: float = 3.5  # and this far into the chat after it, to keep the applause
    switch_penalty: float = 12.0  # cost of changing state, in log-odds units
    bias: float = 0.0  # positive favours music, negative favours chat
    clip: float = 3.0  # cap per-frame evidence so one loud frame cannot dominate


def smooth_states(log_odds: np.ndarray, switch_penalty: float, bias: float = 0.0,
                  clip: float = 3.0) -> np.ndarray:
    """Two-state Viterbi. Returns a boolean array, True where music.

    Score of a path = sum of (evidence while in music) - penalty per switch,
    where evidence = clipped log-odds + bias. Chat contributes 0.
    """
    x = np.clip(np.asarray(log_odds, dtype=float), -clip, clip) + bias
    n = len(x)
    if n == 0:
        return np.zeros(0, dtype=bool)

    # score[s] = best score ending in state s (0 chat, 1 music); back[t, s] = previous state
    back = np.zeros((n, 2), dtype=np.int8)
    score = np.array([0.0, x[0]])
    for t in range(1, n):
        stay_chat, from_music = score[0], score[1] - switch_penalty
        stay_music, from_chat = score[1], score[0] - switch_penalty
        back[t, 0] = 0 if stay_chat >= from_music else 1
        back[t, 1] = 1 if stay_music >= from_chat else 0
        score = np.array([max(stay_chat, from_music), max(stay_music, from_chat) + x[t]])

    states = np.zeros(n, dtype=np.int8)
    states[-1] = int(np.argmax(score))
    for t in range(n - 1, 0, -1):
        states[t - 1] = back[t, states[t]]
    return states.astype(bool)


def runs(states: np.ndarray, hop: float) -> list[Segment]:
    """Contiguous runs of a boolean array as segments in seconds."""
    segs: list[Segment] = []
    if len(states) == 0:
        return segs
    change = np.flatnonzero(np.diff(states.astype(np.int8))) + 1
    bounds = np.concatenate([[0], change, [len(states)]])
    for a, b in zip(bounds[:-1], bounds[1:]):
        segs.append(Segment(a * hop, b * hop, SET if states[a] else CHAT))
    return segs


def _merge_adjacent(segs: list[Segment]) -> list[Segment]:
    out: list[Segment] = []
    for s in segs:
        if out and out[-1].kind == s.kind:
            out[-1].end = s.end
        else:
            out.append(Segment(s.start, s.end, s.kind))
    return out


def enforce_min_durations(segs: list[Segment], min_set: float, min_chat: float) -> list[Segment]:
    """Repeatedly flip the shortest too-short segment into its neighbours' kind.

    Shortest first, so a brief pause inside a long set disappears before a
    brief burst of noodling inside a long chat is considered.
    """
    segs = _merge_adjacent(segs)
    while len(segs) > 1:
        too_short = [
            (s.duration, i) for i, s in enumerate(segs)
            if s.duration < (min_set if s.kind == SET else min_chat)
        ]
        if not too_short:
            break
        _, i = min(too_short)
        segs[i].kind = CHAT if segs[i].kind == SET else SET
        segs = _merge_adjacent(segs)
    # A single segment covering the whole file that is too short to be a set is chat.
    if len(segs) == 1 and segs[0].kind == SET and segs[0].duration < min_set:
        segs[0].kind = CHAT
    return segs


def pad_sets(segs: list[Segment], pad_start: float, pad_end: float) -> list[Segment]:
    """Grow each set into the chat either side so first notes and applause survive.

    A chat between two sets gives up at most half its length to each.
    """
    segs = [Segment(s.start, s.end, s.kind, s.name) for s in segs]
    for i, s in enumerate(segs):
        if s.kind != CHAT:
            continue
        before = i > 0 and segs[i - 1].kind == SET
        after = i + 1 < len(segs) and segs[i + 1].kind == SET
        share = s.duration / (2 if before and after else 1)
        # Never swallow a chat whole; leave at least a sliver.
        if before:
            s.start += min(pad_end, share * 0.9)
            segs[i - 1].end = s.start
        if after:
            s.end -= min(pad_start, share * 0.9)
            segs[i + 1].start = s.end
    return segs


def name_segments(segs: list[Segment]) -> list[Segment]:
    n_set = n_chat = 0
    for s in segs:
        if s.kind == SET:
            n_set += 1
            s.name = f"Set {n_set}"
        else:
            n_chat += 1
            s.name = f"Chat {n_chat}"
    return segs


def segment(log_odds: np.ndarray, hop: float, duration: float,
            params: SegmentParams | None = None) -> list[Segment]:
    """Full pipeline: smooth, enforce minimum lengths, pad, name."""
    p = params or SegmentParams()
    states = smooth_states(log_odds, p.switch_penalty, p.bias, p.clip)
    segs = runs(states, hop)
    if not segs:
        return []
    segs[-1].end = duration  # last frame may be partial
    segs = enforce_min_durations(segs, p.min_set, p.min_chat)
    segs = pad_sets(segs, p.pad_start, p.pad_end)
    return name_segments(segs)
