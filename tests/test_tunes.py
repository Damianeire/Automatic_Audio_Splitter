import numpy as np
import pytest

from synth import DORIAN, SR, set_of, tune
from trad_split import tunes
from trad_split.segment import SET, Mark, Segment


def changes_in(*parts, **kw):
    audio = set_of(*parts, **kw)
    f = tunes.features(audio)
    found, _ = tunes.find_changes(f["chroma"], 0, len(audio) / SR)
    truth = np.cumsum([len(p) for p in parts])[:-1] / SR
    return [c.time for c in found], list(truth)


@pytest.mark.parametrize("parts", [
    [tune(62, seed=1), tune(67, seed=2)],  # D reel into G reel
    [tune(62, seed=1), tune(62, seed=5)],  # two reels in D
    [tune(62, rhythm="jig", seed=1, rounds=3), tune(62, seed=3)],  # jig into reel
    [tune(67, seed=1), tune(69, DORIAN, seed=2), tune(62, seed=3)],  # three reels
], ids=["key-change", "same-key", "jig-to-reel", "three-tunes"])
def test_finds_each_change(parts):
    found, truth = changes_in(*parts)
    assert len(found) == len(truth)
    assert all(abs(f - t) <= 5 for f, t in zip(found, truth))


def test_one_tune_played_three_times_has_no_change():
    found, _ = changes_in(tune(62, seed=1, rounds=3))
    assert found == []


def test_noisy_room():
    found, truth = changes_in(tune(62, seed=7), tune(62, seed=8), tune(67, seed=9), noise=0.15)
    assert len(found) == 2 and all(abs(f - t) <= 5 for f, t in zip(found, truth))


def test_short_set_is_one_tune():
    chroma = np.random.default_rng(0).random((12, 100))
    assert tunes.find_changes(chroma, 0, 50)[0] == []


def test_segment_tunes():
    s = Segment(100, 400, SET, "Set 1", [Mark(230, "Tune 2"), Mark(101, "The Kesh"), Mark(330, "Tune 3 ?")])
    assert s.tunes() == [(100, 230, "The Kesh"), (230, 330, "Tune 2"), (330, 400, "Tune 3 ?")]
    assert Segment(0, 10, SET).tunes() == [(0, 10, "Tune 1")]
