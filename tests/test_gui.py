import tomllib
from pathlib import Path

import pytest

from trad_split import cli
from trad_split.gui_options import (
    NOTE, REAPER, MEMO, ProgressLog, build_argv, initial_options, kind, session_dirs, update_config,
    where_hint,
)


@pytest.fixture
def opts(tmp_path):
    return initial_options(tmp_path / "none.toml")


def parse(argv):
    """What trad-split would make of an argument list, ignoring any config file."""
    return cli.resolve_options(cli.build_parser().parse_args([*argv, "--config", "/nonexistent"]))


def test_kind():
    assert kind(Path("a/Session.RPP")) == REAPER
    assert kind(Path("Session.rpp")) == REAPER
    assert kind(Path("20251122 Session.md")) == NOTE
    assert kind(Path("Session.m4a")) == MEMO
    assert kind(Path("Sessions")) == MEMO


def test_every_option_round_trips(opts):
    opts.update(audio=False, sets_only=True, obsidian=True, force=True, bias=-0.75, min_set=55.0,
                tune_sensitivity=1.5, tune_tail=3.5, output=Path("/out"), vault=Path("/vault"))
    argv = build_argv(opts, Path("memo.m4a"))
    got = parse(argv)
    for key in ["audio", "sets_only", "reaper", "obsidian", "plot", "tunes", "reencode", "force",
                "rescan", "min_set", "min_chat", "pad_start", "pad_end", "switch_penalty", "bias",
                "min_tune", "tune_sensitivity", "tune_tail", "output", "vault"]:
        assert got[key] == opts[key], key
    assert argv[0] == "memo.m4a"


def test_argv_overrides_config(tmp_path, opts):
    config = tmp_path / "config.toml"
    config.write_text("obsidian = true\nbias = 2.0\n")
    argv = build_argv(opts, Path("memo.m4a"))  # opts has obsidian off, bias 0
    got = cli.resolve_options(cli.build_parser().parse_args([*argv, "--config", str(config)]))
    assert got["obsidian"] is False and got["bias"] == 0.0


def test_reaper_item(opts):
    opts["output"] = Path("/elsewhere")
    argv = build_argv(opts, Path("/s/Session.RPP"))
    assert argv[:2] == ["--from-reaper", "/s/Session.RPP"]
    assert not any(a.startswith("--output") for a in argv)  # re-cuts stay beside the project


def test_note_item(opts):
    opts.update(tune_format="m4a", tune_tail=0.0, vault=Path("/v"))
    argv = build_argv(opts, Path("/v/Sessions/20251122 X.md"), include_unnamed=True)
    args = cli.build_parser().parse_args(argv)
    assert args.export_tunes == Path("/v/Sessions/20251122 X.md")
    assert args.tune_format == "m4a" and args.all and args.vault == Path("/v")
    assert args.tune_tail == 0.0  # the export runs tunes past the change by the window's amount


def test_where_hint(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    assert where_hint(None, None, obsidian=False) == ""  # no note, nothing to check
    assert "Choose your vault" in where_hint(vault / "Sessions", None, obsidian=True)
    assert "not an Obsidian vault" in where_hint(vault / "Sessions", tmp_path, obsidian=True)
    assert "next to each recording" in where_hint(None, vault, obsidian=True)
    assert "not inside your vault" in where_hint(tmp_path / "Out", vault, obsidian=True)
    assert where_hint(vault / "Sessions", vault, obsidian=True) == ""


def test_session_dirs():
    out = "Session.m4a\n  3 sets, 12:00 of music in 40:00\n  -> /x/20251122 Session\nother\n"
    assert session_dirs(out) == [Path("/x/20251122 Session")]


def test_progress_log_replaces_carriage_return_lines():
    log = ProgressLog()
    assert log.feed("Session.m4a\n  decoding\n\r  analysing 1/3") == ["Session.m4a", "  decoding"]
    assert log.partial == "  analysing 1/3"
    assert log.feed("\r  analysing 2") == []
    assert log.feed("/3\r  analysing 3/3") == []
    assert log.partial == "  analysing 3/3"
    assert log.feed("\n  3 sets\n") == ["  analysing 3/3", "  3 sets"]
    assert log.partial == ""


def test_update_config_keeps_comments_and_unknown_keys(opts):
    text = ("# my settings\n"
            'output = "~/Sessions"   # where they go\n'
            "obsidian = false\n"
            "clip = 3.0\n"
            "\n[extra]\nbias = 9\n")
    opts.update(obsidian=True, output=None, bias=0.5, force=True)
    new = update_config(text, opts)
    assert "# my settings" in new
    assert '# output = "~/Sessions"   # where they go' in new
    assert "obsidian = true" in new
    cfg = tomllib.loads(new)
    assert cfg["obsidian"] is True and cfg["bias"] == 0.5 and cfg["clip"] == 3.0
    assert cfg["extra"] == {"bias": 9}
    assert "output" not in cfg and "force" not in cfg  # cleared, and per-run only


def test_update_config_new_file_only_writes_changes(opts):
    opts.update(sets_only=True, vault=Path.home() / "Vault")
    cfg = tomllib.loads(update_config("", opts))
    assert cfg == {"sets_only": True, "vault": "~/Vault"}


def test_update_config_single_quoted_paths_with_spaces(opts):
    # TOML 'literal' strings, as people write paths; the space used to split the value.
    text = ("output = '/Users/me/Library/Mobile Documents/Vault/Sessions'  # sessions\n"
            "vault = '/Users/me/Library/Mobile Documents/Vault'\n")
    opts.update(output=Path("/Users/me/Library/Mobile Documents/Vault/Sessions"),
                vault=Path("/Users/me/Library/Mobile Documents/Vault"))
    new = update_config(text, opts)
    assert tomllib.loads(new) == {"output": "/Users/me/Library/Mobile Documents/Vault/Sessions",
                                  "vault": "/Users/me/Library/Mobile Documents/Vault"}
    assert new.splitlines()[0].endswith("  # sessions")


def test_save_config_refuses_to_write_an_invalid_file(tmp_path, opts, monkeypatch):
    from trad_split import gui_options

    config = tmp_path / "config.toml"
    config.write_text("bias = 1.0\n")
    monkeypatch.setattr(gui_options, "update_config", lambda text, o: "bias = 1.0 oops\n")
    with pytest.raises(ValueError, match="left as it was"):
        gui_options.save_config(config, opts)
    assert config.read_text() == "bias = 1.0\n"


def test_saved_config_is_read_back(tmp_path, opts):
    from trad_split.gui_options import save_config

    config = tmp_path / "sub" / "config.toml"
    opts.update(reaper=False, min_set=60.0, tune_format="m4a")
    save_config(config, opts)
    again = initial_options(config)
    assert again["reaper"] is False and again["min_set"] == 60.0 and again["tune_format"] == "m4a"


def test_window_builds(tmp_path, opts, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from trad_split.gui import Window

    app = QApplication.instance() or QApplication([])
    memo = tmp_path / "Session.m4a"
    memo.write_bytes(b"")
    (tmp_path / "notes.txt").write_text("")
    win = Window(opts, config=tmp_path / "config.toml")
    win.add_paths([memo, memo, tmp_path / "notes.txt", tmp_path / "missing.m4a"])
    assert win.files.count() == 1  # duplicates, non-audio and missing files are skipped
    win.checks["obsidian"].setChecked(True)
    win.numbers["bias"].setValue(-1.0)
    got = win.current_options()
    assert got["obsidian"] is True and got["bias"] == -1.0
    assert win.run_btn.isEnabled() and not win.stop_btn.isEnabled()

    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    win.vault_edit.setText(str(vault))
    win.output_check.setChecked(True)
    win.output_edit.setText(str(tmp_path / "elsewhere"))
    assert "not inside your vault" in win.where_warning.text()
    win.output_edit.setText(str(vault / "Sessions"))
    assert win.where_warning.text() == ""
    assert win.current_options()["output"] == vault / "Sessions"
    win.output_check.setChecked(False)  # next to each recording; the typed folder is kept
    assert win.current_options()["output"] is None and win.output_edit.text()
    win.close()
    app.processEvents()
