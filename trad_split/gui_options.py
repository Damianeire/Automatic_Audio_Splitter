"""The parts of the trad-split window that don't need Qt: which options it shows,
how they become a trad-split command, and saving them back to the config file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import cli

# (option, checkbox label)
BOOLS = [
    ("audio", "Audio files"),
    ("sets_only", "Sets only, skip chat"),
    ("reaper", "Reaper project and CSV"),
    ("obsidian", "Obsidian note"),
    ("plot", "Score plot"),
    ("tunes", "Mark tune changes"),
    ("reencode", "Re-encode (AAC 192k)"),
    ("force", "Overwrite existing project and note"),
    ("rescan", "Rescan, ignore cached scores"),
]

# (option, label, minimum, maximum, step, decimals)
NUMBERS = [
    ("min_set", "Shortest set (s)", 0, 600, 5, 1),
    ("min_chat", "Shortest chat (s)", 0, 120, 1, 1),
    ("pad_start", "Keep before set (s)", 0, 30, 0.5, 1),
    ("pad_end", "Keep after set (s)", 0, 30, 0.5, 1),
    ("switch_penalty", "Switch penalty", 0, 100, 1, 1),
    ("bias", "Bias (+ music, - chat)", -5, 5, 0.25, 2),
    ("min_tune", "Shortest tune (s)", 10, 600, 5, 1),
    ("tune_sensitivity", "Tune sensitivity", 0.1, 5, 0.1, 2),
]

TUNE_FORMATS = ["mp3", "m4a"]

# Per-run switches that are never saved as defaults.
PER_RUN = {"force", "rescan"}
SAVED = [k for k, _ in BOOLS if k not in PER_RUN] + [k for k, *_ in NUMBERS] + [
    "output", "vault", "tune_format"]

MEMO, REAPER, NOTE = "memo", "reaper", "note"
DESCRIPTIONS = {MEMO: "split", REAPER: "re-cut from Reaper", NOTE: "export tunes"}


def initial_options(config: Path = cli.CONFIG_PATH) -> dict:
    """Defaults with the config file on top, as a plain trad-split run would see them."""
    return cli.resolve_options(cli.build_parser().parse_args(["--config", str(config)]))


def kind(path: Path) -> str:
    """What running this item means, as in scripts/finder-quick-action.sh."""
    suffix = Path(path).suffix.lower()
    if suffix == ".rpp":
        return REAPER
    if suffix == ".md":
        return NOTE
    return MEMO


def _flag(key: str) -> str:
    return key.replace("_", "-")


def build_argv(opts: dict, item: Path, *, include_unnamed: bool = False) -> list[str]:
    """trad-split arguments for one list item.

    Every option shown in the window is passed explicitly, so the run does what
    the window shows whatever the config file says.
    """
    item = Path(item)
    what = kind(item)
    if what == NOTE:
        argv = ["--export-tunes", str(item), f"--tune-format={opts['tune_format']}",
                "--force" if opts["force"] else "--no-force"]
        if opts.get("tunes_folder"):
            argv.append(f"--tunes-folder={opts['tunes_folder']}")
        if opts.get("vault"):
            argv.append(f"--vault={opts['vault']}")
        if include_unnamed:
            argv.append("--all")
        return argv

    argv = ["--from-reaper", str(item)] if what == REAPER else [str(item)]
    argv += [("--" if opts[key] else "--no-") + _flag(key) for key, _ in BOOLS]
    # '=' so a negative bias is not mistaken for a flag.
    argv += [f"--{_flag(key)}={float(opts[key]):g}" for key, *_ in NUMBERS]
    if opts.get("output") and what == MEMO:
        argv.append(f"--output={opts['output']}")
    if opts.get("vault"):
        argv.append(f"--vault={opts['vault']}")
    if opts.get("device") and opts["device"] != "auto":
        argv.append(f"--device={opts['device']}")
    if opts.get("model"):
        argv.append(f"--model={opts['model']}")
    return argv


def session_dirs(output: str) -> list[Path]:
    """Session folders a run reported with its '  -> <dir>' lines."""
    return [Path(m) for m in re.findall(r"^  -> (.+?)\s*$", output, re.MULTILINE)]


class ProgressLog:
    """Turns process output into log lines.

    Progress lines start with a carriage return and replace each other, so they
    are held as the unfinished last line until a newline commits them.
    """

    def __init__(self) -> None:
        self.partial = ""

    def feed(self, text: str) -> list[str]:
        """Add output; return the lines it completed. self.partial is the line in progress."""
        done = []
        for piece in re.split(r"(\r|\n)", text):
            if piece == "\n":
                done.append(self.partial)
                self.partial = ""
            elif piece == "\r":
                self.partial = ""
            else:
                self.partial += piece
        return done


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value))
    if isinstance(value, Path):
        home = str(Path.home())
        value = str(value)
        if value == home or value.startswith(home + "/"):
            value = "~" + value[len(home):]
    return json.dumps(str(value))


_ASSIGNMENT = re.compile(r'^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)("(?:[^"\\]|\\.)*"|[^#\s]+)(.*)$')


def update_config(text: str, opts: dict) -> str:
    """Write the saved options into config file text, keeping its comments.

    Keys already in the file are updated in place. Other keys are added only
    when they differ from the built-in default. A cleared folder comments its
    line out.
    """
    lines = text.splitlines()
    top = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
    seen = set()
    for i, line in enumerate(lines[:top]):  # trad-split only reads top-level keys
        m = _ASSIGNMENT.match(line)
        key = m.group(2).replace("-", "_") if m else None
        if key not in SAVED or key in seen:
            continue
        seen.add(key)
        if opts.get(key) is None:
            lines[i] = f"# {line.lstrip()}"
        else:
            lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{_toml_value(opts[key])}{m.group(5)}"
    extra = [f"{key} = {_toml_value(opts[key])}" for key in SAVED
             if key not in seen and opts.get(key) is not None and opts[key] != cli.DEFAULTS[key]]
    if extra:
        head, tail = lines[:top], lines[top:]
        while head and not head[-1].strip():
            head.pop()
        lines = head + ([""] if head else []) + extra + ([""] if tail else []) + tail
    return "\n".join(lines) + "\n"


def save_config(path: Path, opts: dict) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(update_config(text, opts), encoding="utf-8")
