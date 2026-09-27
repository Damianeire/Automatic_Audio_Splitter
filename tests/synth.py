"""Synthetic trad-ish tunes for testing tune-change detection.

Each tune is two 8-bar parts, played AABB, the whole tune repeated.
Melodies are seeded random walks on a scale, so different seeds give
different tunes in the same key.
"""

import numpy as np

SR = 22050
MAJOR = [0, 2, 4, 5, 7, 9, 11]
DORIAN = [0, 2, 3, 5, 7, 9, 10]


def _note(freq: float, dur: float, accent: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    wave = sum(np.sin(2 * np.pi * freq * h * t) / h for h in range(1, 6))
    return accent * wave * np.exp(-3.0 * t) * np.minimum(1, t * 200)


def _part(rng, scale, root, notes_per_bar, beat_every, eighth):
    degrees = np.clip(np.cumsum(rng.choice([-2, -1, -1, 1, 1, 2, 0], 8 * notes_per_bar)) + 7, 0, 14)
    # Resolve each part's last bar to the tonic.
    degrees[-notes_per_bar:] = [7] * notes_per_bar
    out = []
    for i, d in enumerate(degrees):
        midi = root + 12 * (d // 7) + scale[d % 7]
        freq = 440.0 * 2 ** ((midi - 69) / 12)
        out.append(_note(freq, eighth, 1.0 if i % beat_every == 0 else 0.6))
    return np.concatenate(out)


def tune(root=62, scale=MAJOR, rhythm="reel", seed=0, rounds=2, bpm=112):
    rng = np.random.default_rng(seed)
    if rhythm == "reel":  # 4/4, even quavers, 8 per bar
        notes_per_bar, beat_every, eighth = 8, 2, 30 / bpm
    else:  # jig: 6/8, two groups of three per bar
        notes_per_bar, beat_every, eighth = 6, 3, 20 / bpm
    a = _part(rng, scale, root, notes_per_bar, beat_every, eighth)
    b = _part(rng, scale, root + 0, notes_per_bar, beat_every, eighth)
    once = np.concatenate([a, a, b, b])
    return np.tile(once, rounds)


def set_of(*tunes, noise=0.02, seed=0):
    audio = np.concatenate(tunes)
    audio = audio / np.abs(audio).max() * 0.5
    audio += noise * np.random.default_rng(seed).standard_normal(len(audio))
    return audio.astype(np.float32)
