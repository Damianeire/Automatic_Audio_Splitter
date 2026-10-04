import json
import re
import shutil
import subprocess

import pytest

from trad_split import cli
from trad_split.audio import duration, probe
from trad_split.export import export_tunes, parse_note

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def tone(path, seconds, codec):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}",
                    "-c:a", codec, str(path)], check=True)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Trad Tunes Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text(json.dumps({"attachmentFolderPath": "Sound Files"}))
    session = v / "Sessions" / "20251122 The Clock Tavern 22"
    session.mkdir(parents=True)
    tone(session / "02 Set 1.m4a", 120, "aac")
    tone(session / "04 Set 2.mp3", 90, "libmp3lame")
    (session / "20251122 The Clock Tavern 22.md").write_text("""---
type: session
date: 2025-11-22
---

# 20251122 The Clock Tavern 22

## Set 1
![[Sessions/20251122 The Clock Tavern 22/02 Set 1.m4a]]
```loops
file: Sessions/20251122 The Clock Tavern 22/02 Set 1.m4a
0:00 - 0:40.5 | The Silver Spear
0:40.5 - 1:20 | Tune 2 ?
1:20 - 2:00 | The Mason's Apron ?
```

## Set 2
```loops
file: 04 Set 2.mp3
0:00 - 0:45 | The Kesh
0:45 | The Silver Spear
```
""")
    tunes = v / "Tunes"
    tunes.mkdir()
    (tunes / "The Silver Spear.md").write_text("# The Silver Spear\n\nReel in D.\n\n## Recordings\n- old one\n\n## Notes\nx\n")
    (tunes / "the kesh.md").write_text("# The Kesh\nJig in G.\n")
    return v


def note_of(vault):
    return vault / "Sessions" / "20251122 The Clock Tavern 22" / "20251122 The Clock Tavern 22.md"


def test_parse_note(vault):
    sections, date = parse_note(note_of(vault), vault)
    assert date == "20251122"
    assert [(s.set_file.name, s.start, s.end, s.name) for s in sections] == [
        ("02 Set 1.m4a", 0, 40.5, "The Silver Spear"),
        ("02 Set 1.m4a", 40.5, 80, "Tune 2 ?"),
        ("02 Set 1.m4a", 80, 120, "The Mason's Apron ?"),
        ("04 Set 2.mp3", 0, 45, "The Kesh"),
        ("04 Set 2.mp3", 45, None, "The Silver Spear"),
    ]
    assert all(s.set_file.exists() for s in sections)  # vault-relative and note-relative paths


def test_export(vault):
    report = export_tunes(note_of(vault))
    sounds = vault / "Sound Files"
    assert sorted(p.name for p in sounds.iterdir()) == [
        "20251122 The Kesh.mp3", "20251122 The Mason's Apron.mp3",
        "20251122 The Silver Spear (2).mp3", "20251122 The Silver Spear.mp3"]
    assert report.unnamed == 1
    assert abs(duration(sounds / "20251122 The Silver Spear.mp3") - 42.5) < 0.2  # 2 s into the next tune
    assert abs(duration(sounds / "20251122 The Mason's Apron.mp3") - 40) < 0.2  # no next tune: file end
    assert abs(duration(sounds / "20251122 The Silver Spear (2).mp3") - 45) < 0.2  # to end of file
    tags = probe(sounds / "20251122 The Kesh.mp3")["format"]["tags"]
    assert tags["title"] == "The Kesh" and tags["album"] == "20251122 The Clock Tavern 22"
    assert probe(sounds / "20251122 The Silver Spear.mp3")["streams"][0]["codec_name"] == "mp3"

    spear = (vault / "Tunes" / "The Silver Spear.md").read_text()
    assert spear == ("# The Silver Spear\n\nReel in D.\n\n## Recordings\n- old one\n"
                     "- ![[20251122 The Silver Spear.mp3]] from [[20251122 The Clock Tavern 22]]\n"
                     "- ![[20251122 The Silver Spear (2).mp3]] from [[20251122 The Clock Tavern 22]]\n"
                     "\n## Notes\nx\n")
    kesh = (vault / "Tunes" / "the kesh.md").read_text()
    assert kesh.endswith("\n## Recordings\n- ![[20251122 The Kesh.mp3]] from [[20251122 The Clock Tavern 22]]\n")
    assert report.no_note == ["The Mason's Apron"]
    assert "Exported 4 tunes" in report.summary()

    again = export_tunes(note_of(vault))  # safe to re-run
    assert again.exported == [] and len(again.existing) == 4 and again.linked == []
    assert (vault / "Tunes" / "The Silver Spear.md").read_text() == spear


def test_force_m4a_and_unnamed(vault):
    report = export_tunes(note_of(vault), fmt="m4a", include_unnamed=True, folder="Audio")
    names = sorted(p.name for p in (vault / "Audio").iterdir())
    assert "20251122 Tune 2.m4a" in names and len(names) == 5
    assert report.unnamed == 0
    assert probe(vault / "Audio" / "20251122 The Kesh.m4a")["streams"][0]["codec_name"] == "aac"
    before = (vault / "Audio" / "20251122 The Kesh.m4a").stat().st_mtime_ns
    assert export_tunes(note_of(vault), fmt="m4a", folder="Audio", force=True).existing == []
    assert (vault / "Audio" / "20251122 The Kesh.m4a").stat().st_mtime_ns != before


def test_cli_prints_summary(vault, capsys, tmp_path):
    assert cli.main(["--export-tunes", str(note_of(vault)), "--config", str(tmp_path / "none.toml")]) == 0
    assert capsys.readouterr().out.startswith("Exported 4 tunes; linked 3")


def test_note_without_loops(tmp_path, capsys):
    note = tmp_path / "plain.md"
    note.write_text("# nothing here\n")
    assert cli.main(["--export-tunes", str(note), "--config", str(tmp_path / "none.toml")]) == 0
    assert "No loops blocks" in capsys.readouterr().out


def test_run_from_a_tunes_own_note_links_it_there(vault):
    tune_note = vault / "Tunes" / "The Castle.md"
    tune_note.write_text("""---
type: Reel
---
# The Castle

![[Sessions/20251122 The Clock Tavern 22/02 Set 1.m4a]]
```loops
file: Sessions/20251122 The Clock Tavern 22/02 Set 1.m4a
0:00 - 0:40 | The Castle
0:40 - 1:20 | The Silver Spear
1:20 - 2:00 | Lucy Farr's
```
""")
    report = export_tunes(tune_note)
    assert "The Castle" in report.linked and report.no_note == ["Lucy Farr's"]
    text = tune_note.read_text()
    # No date: in a tune note, so the prefix is the recording's own date.
    assert re.search(r"```\n\n## Recordings\n- !\[\[\d{8} The Castle\.mp3\]\]\n$", text)  # no "from" itself
    spear = (vault / "Tunes" / "The Silver Spear.md").read_text()
    assert re.search(r"- !\[\[\d{8} The Silver Spear\.mp3\]\] from \[\[The Castle\]\]", spear)
    assert export_tunes(tune_note).linked == [] and tune_note.read_text() == text  # safe to re-run
