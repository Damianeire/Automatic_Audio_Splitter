import shutil
import subprocess

import pytest

from synth import SR, set_of, tune
from trad_split import cli
from trad_split.loops import add_loops

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def write_set(path, *tunes_):
    audio = set_of(*tunes_)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "libmp3lame" if path.suffix == ".mp3" else "aac", str(path)], input=audio.tobytes(), check=True)
    return len(tunes_[0]) / SR  # where the second tune starts


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr("trad_split.classify.CACHE_DIR", tmp_path / "cache")
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / "Sound Files").mkdir()
    change = write_set(v / "Sound Files" / "Ballina reels.m4a", tune(62, seed=1), tune(67, seed=2))
    write_set(v / "Sound Files" / "Done.m4a", tune(62, seed=3))
    (v / "Practice.md").write_text(
        "# Practice\n\n![[Ballina reels.m4a]]\nSome notes.\n\n"
        "![[Done.m4a]]\n```loops\nfile: Sound Files/Done.m4a\n0:00 - 1:00 | The Kesh\n```\n\n"
        "```\n![[Ballina reels.m4a]]\n```\n![[Missing.m4a]]\n")
    return v, change


def test_adds_block_under_new_embeds_only(vault):
    v, change = vault
    report = add_loops(v / "Practice.md")
    text = (v / "Practice.md").read_text()
    head, rest = text.split("```loops\nfile: Sound Files/Ballina reels.m4a\n", 1)
    assert head == "# Practice\n\n![[Ballina reels.m4a]]\n"
    block, after = rest.split("```\n", 1)
    first, second = block.splitlines()
    t = first.split(" - ")[1].split(" | ")[0]
    m, s = t.split(":")
    assert abs(int(m) * 60 + float(s) - change) <= 5
    assert first.startswith("0:00 - ") and first.endswith("| Tune 1")
    assert second.startswith(f"{t} - ") and "| Tune 2" in second
    assert after.startswith("Some notes.\n")
    assert "0:00 - 1:00 | The Kesh" in text  # existing block kept
    assert text.count("```loops") == 2  # nothing added inside the code block
    assert report.kept == ["Done.m4a"] and report.missing == ["Missing.m4a"]
    assert report.summary().startswith("Added loops for Ballina reels.m4a (2 tunes)")

    again = add_loops(v / "Practice.md")  # safe to re-run
    assert again.added == [] and (v / "Practice.md").read_text() == text


def test_redo_replaces_existing(vault, tmp_path, capsys):
    v, _ = vault
    assert cli.main(["--add-loops", str(v / "Practice.md"), "--redo-loops",
                     "--config", str(tmp_path / "none.toml")]) == 0
    assert "Done.m4a (1 tune)" in capsys.readouterr().out
    text = (v / "Practice.md").read_text()
    assert "The Kesh" not in text and text.count("```loops") == 2
    assert "![[Done.m4a]]\n```loops\nfile: Sound Files/Done.m4a\n0:00 - " in text


def test_note_without_audio(tmp_path, capsys):
    note = tmp_path / "plain.md"
    note.write_text("# nothing here\n![[picture.png]]\n")
    assert cli.main(["--add-loops", str(note), "--config", str(tmp_path / "none.toml")]) == 0
    assert "No embedded audio files" in capsys.readouterr().out
    assert note.read_text() == "# nothing here\n![[picture.png]]\n"


def test_finds_file_whose_accents_are_stored_differently(tmp_path, monkeypatch):
    import unicodedata

    monkeypatch.setattr("trad_split.classify.CACHE_DIR", tmp_path / "cache")
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    name = "Séamus McGuire, John Lee - Leitrim Clog Dance.mp3"
    folder = v / "Audio" / "Recordings"
    folder.mkdir(parents=True)
    # macOS often stores the decomposed form; the note has the composed one.
    write_set(folder / unicodedata.normalize("NFD", name), tune(62, seed=1))
    note = v / "Tunes" / "Leitrim Clog.md"
    note.parent.mkdir()
    note.write_text(f"# Leitrim Clog\n\n![[{unicodedata.normalize('NFC', name)}]]\n")
    report = add_loops(note)
    assert report.missing == [] and len(report.added) == 1
    assert f"file: Audio/Recordings/{unicodedata.normalize('NFC', name)}\n" in note.read_text()
