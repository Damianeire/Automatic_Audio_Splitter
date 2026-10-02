"""Add a loops block under each audio file embedded in a note.

Works on any note, not just the session notes trad-split writes: every
embedded audio file (![[Some Set.m4a]]) that has no ```loops block under it
is treated as one set, its tune changes are detected, and a block for the
audio-loop-player plugin is inserted on the line below the embed. Sections
are named Tune 1, Tune 2 and so on, ready to be renamed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import audio
from .export import _resolve, find_vault
from .outputs import loops_block
from .segment import SET, Mark, Segment

_EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
_FENCE = re.compile(r"^\s*```")


@dataclass
class LoopsReport:
    added: list[str] = field(default_factory=list)  # "Set 1.m4a (3 tunes)"
    kept: list[str] = field(default_factory=list)  # already had a loops block
    missing: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not (self.added or self.kept or self.missing):
            return "No embedded audio files found in this note."
        parts = []
        if self.added:
            parts.append(f"Added loops for {', '.join(self.added)}")
        if self.kept:
            parts.append(f"already had loops: {', '.join(self.kept)}")
        if self.missing:
            parts.append(f"file not found: {', '.join(self.missing)}")
        return "; ".join(parts) + "."


def _audio_embed(line: str) -> str | None:
    """The link of the audio file embedded on this line, if any."""
    for m in _EMBED.finditer(line):
        if Path(m.group(1).strip()).suffix.lower() in audio.AUDIO_EXTS:
            return m.group(1).strip()
    return None


def _existing_block(lines: list[str], i: int) -> tuple[int, int] | None:
    """(start, end) line span of a ```loops block directly under line i, blank lines allowed."""
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not lines[j].strip().startswith("```loops"):
        return None
    k = j + 1
    while k < len(lines) and not _FENCE.match(lines[k]):
        k += 1
    return j, min(k + 1, len(lines))


def detect(path: Path, *, min_tune: float = 60.0, sensitivity: float = 1.0,
           rescan: bool = False) -> Segment:
    """The whole file as one set, with a Mark at each tune change."""
    from . import classify, tunes

    length = audio.duration(path)
    cache = classify.cache_path(path).with_suffix(".chroma.npz")
    size = path.stat().st_size
    feats = None if rescan else classify.load_scores(cache, size)
    if feats is None:
        print(f"  listening for tune changes in {path.name}", file=sys.stderr)
        feats = tunes.features(audio.decode(path, tunes.SAMPLE_RATE))
        classify.save_scores(cache, feats, size)
    params = tunes.TuneParams(min_tune=min_tune, sensitivity=sensitivity)
    changes, _ = tunes.find_changes(feats["chroma"], 0, length, params, float(feats["hop"]))
    marks = [Mark(c.time, f"Tune {k}" + ("" if c.confident else " ?")) for k, c in enumerate(changes, 2)]
    return Segment(0, length, SET, path.stem, marks)


def add_loops(note: Path, *, vault: Path | None = None, replace: bool = False,
              min_tune: float = 60.0, sensitivity: float = 1.0, rescan: bool = False) -> LoopsReport:
    """Insert a loops block under each embedded audio file in note that lacks one.

    replace=True redoes existing blocks too, which loses any names typed into them.
    """
    note = note.expanduser().resolve()
    vault = find_vault(note, vault).expanduser().resolve()
    lines = note.read_text(encoding="utf-8").split("\n")
    report = LoopsReport()
    out: list[str] = []
    i = 0
    in_code = False
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if _FENCE.match(line):
            in_code = not in_code
        link = None if in_code else _audio_embed(line)
        if link is None:
            i += 1
            continue
        existing = _existing_block(lines, i)
        if existing and not replace:
            report.kept.append(Path(link).name)
            i += 1
            continue
        path = _resolve(link, note, vault)
        if not path.exists():
            report.missing.append(Path(link).name)
            i += 1
            continue
        try:
            file_link = path.resolve().relative_to(vault).as_posix()
        except ValueError:
            file_link = link
        segment = detect(path, min_tune=min_tune, sensitivity=sensitivity, rescan=rescan)
        out += loops_block(file_link, segment)
        n = len(segment.tunes())
        report.added.append(f"{path.name} ({n} tune{'s' if n != 1 else ''})")
        # Skip the old block (and the blank lines before it) when replacing.
        i = existing[1] if existing else i + 1
    if report.added:
        note.write_text("\n".join(out), encoding="utf-8")
    return report
