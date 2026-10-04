"""Export each named tune in a session note to its own audio file.

Reads the ```loops blocks trad-split writes (and you correct) in a session
note, cuts every named section out of its set file as
"yyyymmdd <Tune Name>.mp3" in the vault's sound files folder, and links the
new file from the vault note of the same name.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import audio
from .outputs import loop_time, parse_loop_time

DEFAULT_NAME = re.compile(r"^Tune \d+$")
_BLOCK = re.compile(r"^```loops[ \t]*\n(.*?)^```", re.S | re.M)
_TIME = r"\d+:\d{1,2}(?:\.\d+)?"
_LINE = re.compile(rf"^\s*({_TIME})\s*(?:-\s*({_TIME})\s*)?\|\s*(.+?)\s*$")
_SKIP_DIRS = {".obsidian", ".trash", ".git"}


@dataclass
class Section:
    set_file: Path
    start: float
    end: float | None
    name: str


@dataclass
class Report:
    exported: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    no_note: list[str] = field(default_factory=list)
    unnamed: int = 0
    missing_files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"Exported {len(self.exported)} tune{'s' if len(self.exported) != 1 else ''}"]
        if self.linked:
            parts.append(f"linked {len(self.linked)}")
        if self.existing:
            parts.append(f"already there: {', '.join(self.existing)}")
        if self.no_note:
            parts.append(f"no tune note for: {', '.join(self.no_note)}")
        if self.unnamed:
            parts.append(f"{self.unnamed} still unnamed (Tune N), skipped")
        if self.missing_files:
            parts.append(f"set file not found: {', '.join(self.missing_files)}")
        return "; ".join(parts) + "."


def find_vault(note: Path, configured: Path | None = None) -> Path:
    if configured is not None:
        return configured
    for folder in note.resolve().parents:
        if (folder / ".obsidian").is_dir():
            return folder
    return note.resolve().parent


def _frontmatter_date(text: str) -> str | None:
    """yyyymmdd from the note's frontmatter `date:`."""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        d = re.search(r"^date:\s*['\"]?(\d{4})-(\d{2})-(\d{2})", m.group(1), re.M)
        if d:
            return "".join(d.groups())
    return None


def _key(name: str) -> str:
    """How Obsidian matches names: accents compared by meaning, case ignored.

    macOS can store "é" as e plus a combining accent while the note has the
    single character, so plain string comparison misses the file.
    """
    return unicodedata.normalize("NFC", name).casefold()


def _vault_files(vault: Path, suffix: str | None = None):
    """Every file in the vault outside .obsidian, .trash and .git, shallowest first."""
    found = []
    for root, dirs, names in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        found += [Path(root) / n for n in names if suffix is None or n.lower().endswith(suffix)]
    return sorted(found, key=lambda p: len(p.parts))


def _resolve(link: str, note: Path, vault: Path) -> Path:
    link = link.strip()
    if link.startswith("[[") and link.endswith("]]"):
        link = link[2:-2].split("|")[0]
    for base in (vault, note.parent):
        if (base / link).exists():
            return base / link
    # Bare file name, or a path whose accents are stored differently on disk:
    # Obsidian finds it anywhere in the vault.
    target = _key(link)
    name = _key(Path(link).name)
    files = _vault_files(vault)
    hit = next((f for f in files if _key(f.relative_to(vault).as_posix()) == target), None)
    hit = hit or next((f for f in files if _key(f.name) == name), None)
    return hit or vault / link


def parse_note(note: Path, vault: Path) -> tuple[list[Section], str | None]:
    text = note.read_text(encoding="utf-8")
    sections: list[Section] = []
    for block in _BLOCK.findall(text):
        set_file = None
        for line in block.splitlines():
            if line.strip().lower().startswith("file:"):
                set_file = _resolve(line.split(":", 1)[1], note, vault)
                continue
            m = _LINE.match(line)
            if m and set_file is not None:
                start = parse_loop_time(m.group(1))
                end = parse_loop_time(m.group(2)) if m.group(2) else None
                sections.append(Section(set_file, start, end, m.group(3)))
    return sections, _frontmatter_date(text)


def sounds_folder(vault: Path, note: Path, configured: str | Path | None) -> Path:
    """Where tune files go: config, else Obsidian's attachment folder, else 'Sound Files'."""
    if configured:
        p = Path(configured).expanduser()
        return p if p.is_absolute() else vault / p
    try:
        setting = json.loads((vault / ".obsidian" / "app.json").read_text()).get("attachmentFolderPath")
    except (OSError, ValueError):
        setting = None
    if setting:
        if setting in ("/", ""):
            return vault
        if setting.startswith("./"):
            return note.parent / setting[2:]
        return vault / setting
    return vault / "Sound Files"


def _tune_notes(vault: Path) -> dict[str, Path]:
    notes: dict[str, Path] = {}
    for p in _vault_files(vault, ".md"):
        notes.setdefault(_key(p.stem), p)
    return notes


def add_recording_link(tune_note: Path, line: str, marker: str) -> bool:
    """Add line under '## Recordings' (created if missing). False if marker already linked."""
    text = tune_note.read_text(encoding="utf-8")
    if marker in text:
        return False
    lines = text.rstrip("\n").split("\n")
    heading = next((i for i, l in enumerate(lines) if re.match(r"^##\s+Recordings\s*$", l)), None)
    if heading is None:
        lines += ["", "## Recordings", line]
    else:
        end = heading + 1
        while end < len(lines) and not re.match(r"^#{1,2}\s", lines[end]):
            end += 1
        while end > heading + 1 and not lines[end - 1].strip():
            end -= 1  # keep the blank line before the next heading
        lines.insert(end, line)
    tune_note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def export_tunes(note: Path, *, vault: Path | None = None, folder: str | Path | None = None,
                 fmt: str = "mp3", include_unnamed: bool = False, force: bool = False) -> Report:
    note = note.expanduser().resolve()
    vault = find_vault(note, vault)
    sections, date = parse_note(note, vault)
    report = Report()
    if not sections:
        return report

    dest = sounds_folder(vault, note, folder)
    dest.mkdir(parents=True, exist_ok=True)
    notes = _tune_notes(vault)
    session = note.stem
    seen: dict[str, int] = {}
    durations: dict[Path, float] = {}

    for sec in sections:
        name = re.sub(r"\s*\?$", "", sec.name).strip()
        if DEFAULT_NAME.match(name) and not include_unnamed:
            report.unnamed += 1
            continue
        if not sec.set_file.exists():
            report.missing_files.append(sec.set_file.name)
            continue
        if sec.set_file not in durations:
            durations[sec.set_file] = audio.duration(sec.set_file)
        end = sec.end if sec.end is not None else durations[sec.set_file]

        prefix = date or audio.recorded_at(sec.set_file)[0].strftime("%Y%m%d")
        seen[name] = seen.get(name, 0) + 1
        label = name if seen[name] == 1 else f"{name} ({seen[name]})"
        safe = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", label).strip(" .") or "Untitled"
        dst = dest / f"{prefix} {safe}.{fmt}"

        if dst.exists() and not force:
            report.existing.append(dst.stem)
        else:
            audio.cut(sec.set_file, dst, sec.start, end, codec=audio.codec_for(sec.set_file, dst), tags={
                "title": name, "album": session, "artist": "Session",
                "date": f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:]}",
                "comment": f"from {sec.set_file.name} {loop_time(sec.start)}-{loop_time(end)}",
            })
            report.exported.append(dst.stem)

        # Run from a tune's own note (The Castle), its recording goes in that note too.
        tune_note = notes.get(_key(name))
        source = "" if tune_note == note else f" from [[{session}]]"
        if tune_note is None:
            if name not in report.no_note:
                report.no_note.append(name)
        elif add_recording_link(tune_note, f"- ![[{dst.name}]]{source}", f"[[{dst.name}]]"):
            report.linked.append(name)
    return report
