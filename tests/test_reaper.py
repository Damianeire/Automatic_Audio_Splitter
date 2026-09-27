from pathlib import Path

from trad_split.reaper import read_csv, read_rpp, write_csv, write_rpp
from trad_split.segment import CHAT, SET, Segment


def sample():
    return [Segment(0, 12.5, CHAT, "Chat 1"), Segment(12.5, 300.25, SET, "Set 1"),
            Segment(300.25, 330, CHAT, "Chat 2"), Segment(330, 600, SET, "Set 2")]


def test_rpp_round_trip(tmp_path):
    memo = tmp_path / "Ballina session.m4a"
    memo.write_bytes(b"")
    rpp = tmp_path / "s.RPP"
    write_rpp(rpp, memo, 600, sample())
    text = rpp.read_text()
    assert "<SOURCE VIDEO" in text and '"Set 1" 1' in text
    source, regions = read_rpp(rpp)
    assert source == memo.resolve()
    assert [(r.start, r.end, r.kind, r.name) for r in regions] == \
        [(s.start, s.end, s.kind, s.name) for s in sample()]


def test_rpp_as_reaper_saves_it(tmp_path):
    """Regions renamed, reordered indices, unquoted names, a plain marker, item nudged."""
    rpp = tmp_path / "s.RPP"
    rpp.write_text("""<REAPER_PROJECT 0.1 "7.22/macOS-arm64" 1727000000
  RIPPLE 0
  MARKER 1 12.4 "Set 1 - Silver Spear, Mason's Apron" 1 21929030 1 R {A} 0
  MARKER 1 301 "" 1
  MARKER 7 150 tuning 0 0 1 B {C} 0
  MARKER 3 330.5 'Set 2 "the reels"' 1 0 1 R {B} 0
  MARKER 3 598 "" 1
  MARKER 2 305 Chat 1 0 1 R {D} 0
  MARKER 2 320 "" 1
  <TRACK {X}
    NAME memo
    <ITEM
      POSITION 2
      SNAPOFFS 0
      LENGTH 600
      SOFFS 0
      <SOURCE VIDEO
        FILE "memo.m4a"
      >
    >
  >
>
""")
    source, regions = read_rpp(rpp)
    assert source == (tmp_path / "memo.m4a").resolve()
    assert [r.name for r in regions] == ["Set 1 - Silver Spear, Mason's Apron", "Chat", 'Set 2 "the reels"']
    assert [r.kind for r in regions] == [SET, CHAT, SET]
    assert regions[0].start == 10.4 and regions[0].end == 299  # item moved 2 s right


def test_csv_round_trip(tmp_path):
    p = tmp_path / "r.csv"
    write_csv(p, sample())
    got = read_csv(p)
    assert [(s.start, s.end, s.kind, s.name) for s in got] == \
        [(s.start, s.end, s.kind, s.name) for s in sample()]


def test_csv_reaper_export_with_clock_times(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("#,Name,Start,End,Length\nM1,tuning,1:00.000,,\n"
                 "R1,Set 1,0:12.500,5:00.250,4:47.750\nR2,Chat,5:00.250,5:30.000,0:29.750\n")
    got = read_csv(p)
    assert [(s.start, s.end, s.kind) for s in got] == [(12.5, 300.25, SET), (300.25, 330, CHAT)]
