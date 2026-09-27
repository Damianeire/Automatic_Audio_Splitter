"""Set up the Export tunes command in an Obsidian vault's Templater plugin.

Copies the template into Templater's templates folder and adds the
export_tunes user system command, so nothing has to be clicked through by
hand. Obsidian must be closed: Templater keeps its settings in memory and
would write the old ones back over ours.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).parent / "obsidian" / "Export tunes.md"
FUNCTION = "export_tunes"
MIN_TIMEOUT = 120


class SetupError(RuntimeError):
    pass


def obsidian_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def trad_split_command() -> str:
    """Absolute path of this install's trad-split, which Templater will call."""
    exe = Path(sys.executable).parent / "trad-split"
    if not exe.exists():
        found = shutil.which("trad-split")
        exe = Path(found) if found else exe
    return str(exe)


def setup(vault: Path, *, command: str | None = None) -> list[str]:
    """Install the template and Templater function. Returns what was done."""
    if obsidian_running():
        raise SetupError("Obsidian is open. Quit it (Cmd+Q) and run this again.")
    vault = vault.expanduser()
    settings_path = vault / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
    if not settings_path.parent.is_dir():
        raise SetupError(f"Templater is not installed in {vault}. Install and enable it first "
                         "(Settings > Community plugins > Browse > Templater).")
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    done: list[str] = []

    folder = (settings.get("templates_folder") or "").strip("/") or "Templates"
    if settings.get("templates_folder") != folder:
        settings["templates_folder"] = folder
        done.append(f"set Templater's template folder to '{folder}'")
    target = vault / folder / TEMPLATE.name
    target.parent.mkdir(parents=True, exist_ok=True)
    new = TEMPLATE.read_text(encoding="utf-8")
    if not target.exists():
        target.write_text(new, encoding="utf-8")
        done.append(f"copied the template to {folder}/{TEMPLATE.name}")
    elif target.read_text(encoding="utf-8") != new:
        shutil.copy2(target, target.with_name(target.name + ".bak"))
        target.write_text(new, encoding="utf-8")
        done.append(f"updated {folder}/{TEMPLATE.name} (old copy kept as .bak)")

    if settings.get("enable_system_commands") is not True:
        settings["enable_system_commands"] = True
        done.append("turned on user system command functions")
    if float(settings.get("command_timeout") or 0) < MIN_TIMEOUT:
        settings["command_timeout"] = MIN_TIMEOUT
        done.append(f"set the command timeout to {MIN_TIMEOUT} s")

    cmd = f'"{command or trad_split_command()}" --export-tunes "$note"'
    pairs = [p for p in settings.get("templates_pairs", []) if p and any(p) and p[0] != FUNCTION]
    old = next((p for p in settings.get("templates_pairs", []) if p and p[0] == FUNCTION), None)
    if old != [FUNCTION, cmd]:
        done.append(f"{'updated' if old else 'added'} the {FUNCTION} function")
    settings["templates_pairs"] = pairs + [[FUNCTION, cmd]]

    hotkey = f"{folder}/{TEMPLATE.name}"
    hotkeys = [h for h in settings.get("enabled_templates_hotkeys", []) if h]
    if hotkey not in hotkeys:
        hotkeys.append(hotkey)
        done.append("registered Export tunes as a command you can give a hotkey")
    settings["enabled_templates_hotkeys"] = hotkeys

    if done:
        if settings_path.exists():
            shutil.copy2(settings_path, settings_path.with_name("data.json.bak"))
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return done
