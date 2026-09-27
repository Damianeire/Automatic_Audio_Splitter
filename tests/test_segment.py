import numpy as np

from trad_split.segment import CHAT, SET, SegmentParams, enforce_min_durations, pad_sets, runs, segment, smooth_states

HOP = 0.5


def frames(*parts):
    """Build log-odds from (seconds, value) pieces."""
    return np.concatenate([np.full(int(sec / HOP), val, dtype=float) for sec, val in parts])


def kinds(segs):
    return [s.kind for s in segs]


def test_basic_set_chat_set():
    lo = frames((60, 3), (20, -3), (90, 3))
    segs = segment(lo, HOP, 170, SegmentParams(pad_start=0, pad_end=0))
    assert kinds(segs) == [SET, CHAT, SET]
    assert [s.name for s in segs] == ["Set 1", "Chat 1", "Set 2"]
    assert abs(segs[1].start - 60) <= 1 and abs(segs[1].end - 80) <= 1
    assert segs[-1].end == 170


def test_flicker_inside_set_is_ignored():
    rng = np.random.default_rng(0)
    lo = frames((120, 2.5))
    lo[rng.choice(len(lo), 30, replace=False)] = -3  # someone talks over the tune now and then
    segs = segment(lo, HOP, 120)
    assert kinds(segs) == [SET]


def test_talking_over_a_quiet_bar_stays_in_set():
    lo = frames((60, 3), (3, -3), (60, 3))
    assert kinds(segment(lo, HOP, 123)) == [SET]


def test_short_noodle_in_chat_is_not_a_set():
    lo = frames((30, -3), (15, 3), (30, -3), (80, 3))
    segs = segment(lo, HOP, 155)
    assert kinds(segs) == [CHAT, SET]
    assert abs(segs[1].start - 75) <= 2


def test_all_chat():
    segs = segment(frames((100, -2)), HOP, 100)
    assert kinds(segs) == [CHAT] and segs[0].end == 100


def test_short_file_of_music_is_chat():
    assert kinds(segment(frames((10, 3)), HOP, 10)) == [CHAT]


def test_empty():
    assert segment(np.array([]), HOP, 0) == []


def test_bias_shifts_decision():
    lo = frames((60, 0.3), (60, -0.3), (60, 0.3))
    assert kinds(segment(lo, HOP, 180, SegmentParams(bias=1))) == [SET]
    assert kinds(segment(lo, HOP, 180, SegmentParams(bias=-1))) == [CHAT]


def test_viterbi_prefers_single_switch():
    states = smooth_states(frames((10, -3), (10, 3)), switch_penalty=5)
    assert states[:18].sum() == 0 and states[22:].all()


def test_min_duration_flips_shortest_first():
    segs = runs(np.array([1] * 100 + [0] * 4 + [1] * 100 + [0] * 60, dtype=bool), 1.0)
    out = enforce_min_durations(segs, min_set=40, min_chat=10)
    assert kinds(out) == [SET, CHAT]
    assert out[0].end == 204


def test_padding_is_asymmetric():
    segs = runs(np.array([0] * 20 + [1] * 60 + [0] * 30 + [1] * 60 + [0] * 20, dtype=bool), 1.0)
    out = pad_sets(segs, pad_start=1.5, pad_end=3.5)
    assert [(s.start, s.end) for s in out] == [
        (0, 18.5), (18.5, 83.5), (83.5, 108.5), (108.5, 173.5), (173.5, 190)]


def test_padding_never_swallows_a_short_chat():
    segs = runs(np.array([1] * 60 + [0] * 3 + [1] * 60, dtype=bool), 1.0)
    out = pad_sets(segs, pad_start=2, pad_end=5)
    chat = out[1]
    assert chat.duration > 0
    assert out[0].end == chat.start and chat.end == out[2].start
    assert chat.start == 60 + 1.35 and chat.end == 63 - 1.35


def test_segments_are_contiguous():
    rng = np.random.default_rng(1)
    lo = np.repeat(rng.choice([-3, 3], 40), 60)  # 40 random 30 s blocks
    segs = segment(lo, HOP, len(lo) * HOP)
    assert segs[0].start == 0 and segs[-1].end == len(lo) * HOP
    for a, b in zip(segs, segs[1:]):
        assert a.end == b.start and a.kind != b.kind
