"""Find where one tune gives way to the next inside a set.

A tune is played round two or three times (AABB each round), so once the
first round is over, the music keeps matching something heard a minute or
so earlier. When the next tune starts, that stops: the new material has
not been heard before. We track, every half second, how well the music
matches anything in the preceding ~2.5 minutes, and mark a change where a
long stretch of repeating music is followed by unheard material.

This works whether or not the key or rhythm changes, but needs each tune
to be played at least twice through. The A-to-B change inside a tune's
first round also looks new, which is why a change must follow a long
repeating stretch and be at least min_tune after the previous one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 22050
HOP = 0.5  # seconds per feature frame, same as the music/chat scores
_STFT_HOP = 512


@dataclass
class TuneParams:
    min_tune: float = 60.0  # seconds between changes (a tune is at least two rounds)
    edge: float = 30.0  # no change this close to the start or end of a set
    sensitivity: float = 1.0  # higher finds more changes


@dataclass
class TuneChange:
    time: float  # seconds from the start of the recording
    strength: float  # size of the drop in repetition, 0..2

    @property
    def confident(self) -> bool:
        return self.strength >= 0.4


def features(audio: np.ndarray, sr: int = SAMPLE_RATE) -> dict[str, np.ndarray]:
    """Chroma per HOP-second frame for a whole recording."""
    import librosa

    chroma = librosa.feature.chroma_cqt(y=audio, sr=sr, hop_length=_STFT_HOP, bins_per_octave=36)
    n_out = int(np.ceil(len(audio) / sr / HOP))
    edges = np.minimum(np.round(np.arange(n_out + 1) * HOP * sr / _STFT_HOP).astype(int), chroma.shape[1])
    pooled = np.zeros((12, n_out), dtype=np.float32)
    for i in range(n_out):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        if a < chroma.shape[1]:
            pooled[:, i] = chroma[:, a:b].mean(axis=1)
    return {"chroma": pooled, "hop": np.float32(HOP)}


def _smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return x
    k = np.hanning(width + 2)[1:-1]
    return np.stack([np.convolve(row, k / k.sum(), mode="same") for row in x])


def repetition(chroma: np.ndarray, hop: float = HOP, window: float = 8.0,
               min_lag: float = 12.0, max_lag: float = 160.0) -> np.ndarray:
    """For each frame, how closely the `window` seconds around it match any earlier passage.

    1 = heard before almost exactly, around 0 or below = new material.
    Frames with nothing far enough back to compare get -1.
    """
    c = _smooth(chroma, 2)
    c = c - c.mean(axis=1, keepdims=True)
    c /= np.maximum(np.linalg.norm(c, axis=0, keepdims=True), 1e-9)
    ssm = c.T @ c
    n = ssm.shape[0]
    w = max(1, int(window / hop))
    box = np.ones(w) / w
    best = np.full(n, -1.0)
    for lag in range(int(min_lag / hop), min(int(max_lag / hop), n)):
        diag = np.diagonal(ssm, -lag)  # diag[j] = similarity of frame j+lag with frame j
        if len(diag) < w:
            break
        # Mean over the window centred on each frame.
        run = np.convolve(diag, box, mode="same")
        best[lag:] = np.maximum(best[lag:], run)
    return best


def _drop(rep: np.ndarray, t: int, left: int, right: int) -> float:
    return rep[t - left:t].mean() - rep[t:t + right].mean()


def find_changes(chroma: np.ndarray, start: float, end: float,
                 params: TuneParams | None = None, hop: float = HOP) -> tuple[list[TuneChange], np.ndarray]:
    """Tune changes between start and end (seconds). Also returns the repetition curve."""
    p = params or TuneParams()
    a, b = max(0, int(start / hop)), min(int(np.ceil(end / hop)), chroma.shape[1])
    if b - a < int(2 * p.edge / hop):
        return [], np.zeros(max(b - a, 0))
    rep = repetition(chroma[:, a:b], hop)
    n = len(rep)

    left, right = int(40 / hop), int(20 / hop)  # a long repeating stretch, then new material
    step = np.zeros(n)
    for t in range(left, n - right):
        step[t] = _drop(rep, t, left, right)

    threshold = 0.25 / p.sensitivity
    edge, gap, fine = int(p.edge / hop), int(p.min_tune / hop), int(8 / hop)
    picked: list[tuple[int, float]] = []
    for t in np.argsort(step)[::-1]:
        strength = float(step[t])
        if strength < threshold:
            break
        # Pin the change to the sharpest local drop, within 20 s.
        lo, hi = max(fine, t - int(20 / hop)), min(n - fine, t + int(20 / hop))
        t = max(range(lo, hi), key=lambda u: _drop(rep, u, fine, fine)) if hi > lo else t
        if t < edge or t >= n - edge:
            continue
        if all(abs(t - u) >= gap for u, _ in picked):
            picked.append((t, strength))
    picked.sort()
    return [TuneChange((a + t) * hop, s) for t, s in picked], rep
