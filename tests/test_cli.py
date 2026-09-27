import shutil
import subprocess

import pytest

from trad_split import cli
from trad_split.reaper import read_rpp

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def memo(tmp_path):
    path = tmp_path / "Session.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=120",
                    "-c:a", "aac", str(path)], check=True)
    return path


def edit_rpp(rpp, memo):
    rpp.write_text(f"""<REAPER_PROJECT 0.1 "7.0" 0
  MARKER 1 5 "Set 1 - Kesh" 1
  MARKER 1 50 "" 1
  MARKER 2 50 "Chat" 1
  MARKER 2 60 "" 1
  MARKER 3 60 "Set 2" 1
  MARKER 3 110 "" 1
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
    note = (session / "Session.md").read_text()
    assert "set_count: 2" in note and "![[03 Set 2.m4a]]" in note
    assert read_rpp(rpp)[1][0].name == "Set 1 - Kesh"  # project untouched
    assert (session / "Session.regions.csv").exists()


def test_sets_only_from_csv(memo, tmp_path):
    csv = tmp_path / "r.csv"
    csv.write_text("#,Name,Start,End\nR1,Chat,0,10\nR2,Set 1,10,70\nR3,Chat,70,80\nR4,Set 2,80,120\n")
    assert cli.main([str(memo), "--from-csv", str(csv), "--sets-only", "--no-reaper",
                     "--config", str(tmp_path / "none.toml")]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.m4a") if p != memo) == ["02 Set 1.m4a", "04 Set 2.m4a"]


def test_config_file(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('output = "~/Trad"\nsets-only = true\nmin_set = 60\n')
    opts = cli.resolve_options(cli.build_parser().parse_args(["x", "--config", str(cfg), "--min-set", "30"]))
    assert opts["sets_only"] is True and opts["min_set"] == 30
    assert str(opts["output"]).endswith("Trad") and "~" not in str(opts["output"])
