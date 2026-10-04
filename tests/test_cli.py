import shutil
import subprocess

import pytest

from trad_split import cli
from trad_split.reaper import read_rpp

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def memo(tmp_path):
    path = tmp_path / "Session.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=120", "-c:a", "aac",
                    "-metadata", "creation_time=2025-11-22T12:00:00Z", str(path)], check=True)
    return path


def probe_chapters(path):
    import json

    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", str(path)],
                         check=True, capture_output=True).stdout
    return json.loads(out)["chapters"]


def edit_rpp(rpp, memo):
    rpp.write_text(f"""<REAPER_PROJECT 0.1 "7.0" 0
  MARKER 1 5 "Set 1 - Kesh" 1
  MARKER 1 50 "" 1
  MARKER 2 50 "Chat" 1
  MARKER 2 60 "" 1
  MARKER 3 60 "Set 2" 1
  MARKER 3 110 "" 1
  MARKER 4 80 "The Silver Spear" 0
  <TRACK
    <ITEM
      POSITION 0
      <SOURCE VIDEO
        FILE "{memo}"
      >
    >
  >
>
""")


def test_recut_from_reaper(memo, tmp_path):
    session = tmp_path / "Session"
    session.mkdir()
    rpp = session / "Session.RPP"
    edit_rpp(rpp, memo)
    (session / "01 Set 1.m4a").write_bytes(b"stale")
    (session / ".trad-split-files").write_text("01 Set 1.m4a\n")

    assert cli.main(["--from-reaper", str(rpp), "--obsidian", "--config", str(tmp_path / "none.toml")]) == 0

    names = sorted(p.name for p in session.glob("*.m4a"))
    assert names == ["01 Set 1 - Kesh.m4a", "02 Chat.m4a", "03 Set 2.m4a"]
    from trad_split.audio import duration
    assert abs(duration(session / "01 Set 1 - Kesh.m4a") - 45) < 0.2
    note = (session / "20251122 Session.md").read_text()
    assert "set_count: 2" in note and "![[03 Set 2.m4a]]" in note
    assert read_rpp(rpp)[1][0].name == "Set 1 - Kesh"  # project untouched
    assert "```loops\nfile: 03 Set 2.m4a\n0:00 - 0:22 | Tune 1\n0:20 - 0:50 | The Silver Spear\n```" in note
    chapters = probe_chapters(session / "03 Set 2.m4a")
    assert [(round(float(c["start_time"])), c["tags"]["title"]) for c in chapters] == \
        [(0, "Tune 1"), (20, "The Silver Spear")]
    assert probe_chapters(session / "01 Set 1 - Kesh.m4a") == []  # one tune, no chapters
    assert (session / "20251122 Session.regions.csv").exists()


def test_sets_only_from_csv(memo, tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text("#,Name,Start,End\nR1,Chat,0,10\nR2,Set 1,10,70\nR3,Chat,70,80\nR4,Set 2,80,120\n")
    assert cli.main([str(memo), "--from-csv", str(csv), "--sets-only", "--no-reaper",
                     "--config", str(tmp_path / "none.toml")]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.m4a") if p != memo) == ["02 Set 1.m4a", "04 Set 2.m4a"]


def test_pad_shortcut_and_specific_pads(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("pad = 2\npad_end = 6\n")
    parse = cli.build_parser().parse_args
    opts = cli.resolve_options(parse(["x", "--config", str(cfg)]))
    assert (opts["pad_start"], opts["pad_end"]) == (2, 6)
    opts = cli.resolve_options(parse(["x", "--config", str(cfg), "--pad", "1"]))
    assert (opts["pad_start"], opts["pad_end"]) == (1, 1)
    opts = cli.resolve_options(parse(["x", "--config", str(tmp_path / "none"), "--pad-end", "4"]))
    assert (opts["pad_start"], opts["pad_end"]) == (1.5, 4)


def test_album_uses_recording_date(tmp_path):
    from datetime import datetime, timezone

    from trad_split.audio import probe, recorded_at

    memo = tmp_path / "Clock.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=30", "-c:a", "aac",
                    "-metadata", "creation_time=2025-11-22T21:40:00Z", str(memo)], check=True)
    expected = datetime(2025, 11, 22, 21, 40, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert recorded_at(memo) == (expected, "file metadata")

    csv = tmp_path / "r.csv"
    csv.write_text("#,Name,Start,End\nR1,Set 1,0,20\n")
    assert cli.main([str(memo), "--from-csv", str(csv), "--no-reaper", "--config", str(tmp_path / "none")]) == 0
    tags = probe(tmp_path / "01 Set 1.m4a")["format"]["tags"]
    assert tags["album"] == f"{expected:%Y%m%d} Clock"


def test_recorded_at_falls_back_to_file_dates(tmp_path):
    from trad_split.audio import recorded_at

    memo = tmp_path / "plain.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", "-fflags", "+bitexact",
                    "-map_metadata", "-1", str(memo)], check=True)
    _, source = recorded_at(memo)
    assert source in ("file created date", "file modified date")


def test_config_file(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('output = "~/Trad"\nsets-only = true\nmin_set = 60\n')
    opts = cli.resolve_options(cli.build_parser().parse_args(["x", "--config", str(cfg), "--min-set", "30"]))
    assert opts["sets_only"] is True and opts["min_set"] == 30
    assert str(opts["output"]).endswith("Trad") and "~" not in str(opts["output"])


def test_cache_path_tracks_memo_changes(tmp_path):
    import os

    from trad_split.classify import cache_path

    memo = tmp_path / "m.m4a"
    memo.write_bytes(b"abc")
    first = cache_path(memo, tmp_path)
    assert first == cache_path(memo, tmp_path)
    os.utime(memo, ns=(0, 10**18))
    assert cache_path(memo, tmp_path) != first


def test_output_elsewhere_reuses_scores_next_to_memo(memo, tmp_path, monkeypatch):
    """Moving output into the vault must not force the model to run again."""
    import numpy as np

    from trad_split import classify

    monkeypatch.setattr(classify, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(classify, "Classifier", None)  # any model use would fail
    hop = 0.5
    log_odds = np.r_[np.full(20, -3.0), np.full(160, 3.0), np.full(60, -3.0)]  # 10 s chat, 80 s set, 30 s chat
    legacy = tmp_path / "Session" / "Session.scores.npz"
    legacy.parent.mkdir()
    classify.save_scores(legacy, {"music": log_odds, "chat": log_odds, "log_odds": log_odds,
                                  "hop": np.float32(hop)}, memo.stat().st_size)

    vault = tmp_path / "Vault"
    assert cli.main([str(memo), "-o", str(vault / "Sessions"), "--vault", str(vault), "--obsidian",
                     "--sets-only", "--no-reaper", "--config", str(tmp_path / "none.toml")]) == 0
    session = vault / "Sessions" / "20251122 Session"
    assert sorted(p.name for p in session.iterdir() if not p.name.startswith(".")) == \
        ["02 Set 1.m4a", "20251122 Session.md"]
    assert "![[Sessions/20251122 Session/02 Set 1.m4a]]" in (session / "20251122 Session.md").read_text()
    assert list((tmp_path / "cache").glob("Session-*.npz"))  # copied into the new cache


def test_bad_config_gives_clear_error(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("output = '/it's broken'\n")
    with pytest.raises(SystemExit, match="not valid TOML"):
        cli.resolve_options(cli.build_parser().parse_args(["x", "--config", str(cfg)]))


def test_session_title_adds_date_once(tmp_path):
    from datetime import datetime

    when = datetime(2025, 11, 22, 21, 40)
    assert cli.session_title(tmp_path / "The Clock Tavern 22.m4a", when) == "20251122 The Clock Tavern 22"
    assert cli.session_title(tmp_path / "20251122 Clock.m4a", when) == "20251122 Clock"
    assert cli.session_title(tmp_path / "20240101 213000.m4a", when) == "20240101 213000"


def test_detects_tunes_end_to_end(tmp_path, monkeypatch):
    """Scores say one long set; tune detection finds the change and it reaches every output."""
    import sys

    import numpy as np

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from synth import SR, set_of, tune

    from trad_split import classify

    audio = set_of(tune(62, seed=1), tune(67, seed=2))
    wav = tmp_path / "raw.wav"
    import wave

    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    memo = tmp_path / "Pub.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac",
                    "-metadata", "creation_time=2025-11-22T12:00:00Z", str(memo)], check=True)

    monkeypatch.setattr(classify, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(classify, "Classifier", None)
    n = int(len(audio) / SR / 0.5) + 1
    lo = np.full(n, 3.0)
    classify.save_scores(classify.cache_path(memo), {"music": lo, "chat": lo, "log_odds": lo,
                                                     "hop": np.float32(0.5)}, memo.stat().st_size)

    assert cli.main([str(memo), "--obsidian", "--reaper", "--config", str(tmp_path / "none.toml")]) == 0
    session = tmp_path / "20251122 Pub"
    set_file = session / "01 Set 1.m4a"
    chapters = probe_chapters(set_file)
    assert [c["tags"]["title"] for c in chapters] == ["Tune 1", "Tune 2"]
    assert abs(float(chapters[1]["start_time"]) - 137.1) < 5
    assert "| Tune 2" in (session / "20251122 Pub.md").read_text()
    regions = read_rpp(session / "20251122 Pub.RPP")[1]
    assert [m.name for m in regions[0].marks] == ["Tune 2"]
