import json

import pytest

from trad_split import cli, obsidian_setup
from trad_split.obsidian_setup import SetupError, setup


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(obsidian_setup, "obsidian_running", lambda: False)
    v = tmp_path / "Vault"
    plugin = v / ".obsidian" / "plugins" / "templater-obsidian"
    plugin.mkdir(parents=True)
    (plugin / "data.json").write_text(json.dumps({
        "command_timeout": 5, "templates_folder": "Meta/Templates", "templates_pairs": [["", ""]],
        "trigger_on_file_creation": True, "enable_system_commands": False,
        "enabled_templates_hotkeys": [""], "folder_templates": [{"folder": "Tunes", "template": "x.md"}],
    }))
    return v


def settings(v):
    return json.loads((v / ".obsidian/plugins/templater-obsidian/data.json").read_text())


def test_setup(vault):
    done = setup(vault, command="/x/trad-split")
    assert len(done) == 5
    s = settings(vault)
    assert s["enable_system_commands"] is True and s["command_timeout"] == 120
    assert s["templates_pairs"] == [["export_tunes", '"/x/trad-split" --export-tunes "$note"']]
    assert s["enabled_templates_hotkeys"] == ["Meta/Templates/Export tunes.md"]
    assert s["trigger_on_file_creation"] is True and s["folder_templates"][0]["folder"] == "Tunes"
    assert "tp.user.export_tunes" in (vault / "Meta/Templates/Export tunes.md").read_text()
    assert (vault / ".obsidian/plugins/templater-obsidian/data.json.bak").exists()

    assert setup(vault, command="/x/trad-split") == []  # idempotent
    assert settings(vault)["templates_pairs"] == s["templates_pairs"]


def test_keeps_other_functions_and_updates_path(vault):
    path = vault / ".obsidian/plugins/templater-obsidian/data.json"
    s = settings(vault)
    s["templates_pairs"] = [["today", "date"], ["export_tunes", "old"]]
    path.write_text(json.dumps(s))
    assert "updated the export_tunes function" in setup(vault, command="/new/trad-split")
    assert settings(vault)["templates_pairs"] == [
        ["today", "date"], ["export_tunes", '"/new/trad-split" --export-tunes "$note"']]


def test_empty_templates_folder_defaults(vault):
    path = vault / ".obsidian/plugins/templater-obsidian/data.json"
    s = settings(vault)
    s["templates_folder"] = ""
    path.write_text(json.dumps(s))
    setup(vault, command="t")
    assert settings(vault)["templates_folder"] == "Templates"
    assert (vault / "Templates/Export tunes.md").exists()


def test_refuses_without_templater_or_with_obsidian_open(vault, tmp_path, monkeypatch):
    with pytest.raises(SetupError, match="Templater is not installed"):
        setup(tmp_path / "Empty")
    monkeypatch.setattr(obsidian_setup, "obsidian_running", lambda: True)
    with pytest.raises(SetupError, match="Quit it"):
        setup(vault)


def test_cli(vault, tmp_path, capsys):
    assert cli.main(["--setup-obsidian", "--vault", str(vault), "--config", str(tmp_path / "n.toml")]) == 0
    assert "added the export_tunes function" in capsys.readouterr().out
    assert settings(vault)["templates_pairs"][0][1].endswith('trad-split" --export-tunes "$note"')
