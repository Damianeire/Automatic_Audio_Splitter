"""Reaper project and regions CSV: write detected segments out, read edits back.

A region named "Chat..." is treated as chat; every other region is a set.
Plain markers inside a set are tune changes, named after the tune they start.
"""

from __future__ import annotations

import csv
import re
import uuid
from pathlib import Path

from .segment import CHAT, SET, Mark, Segment

# Reaper stores colours as native 0xBBGGRR with bit 24 set to mean "custom colour".
SET_RGB = (70, 160, 90)
CHAT_RGB = (140, 140, 140)

SOURCE_TYPES = {
    ".wav": "WAVE", ".aif": "WAVE", ".aiff": "WAVE",
    ".mp3": "MP3", ".flac": "FLAC", ".ogg": "VORBIS", ".opus": "OPUS",
}


def reaper_colour(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return r | (g << 8) | (b << 16) | 0x1000000


def kind_from_name(name: str) -> str:
    return CHAT if name.strip().lower().startswith("chat") else SET


def _quote(s: str) -> str:
    # Reaper quotes with ", or ' / ` when the text itself contains ".
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    return "`" + s.replace("`", "'") + "`"


def _attach_marks(segments: list[Segment], marks: list[Mark]) -> None:
    """Give each set the markers that fall inside it (or within 2 s of its start)."""
    for s in segments:
        if s.kind == SET:
            s.marks = [m for m in marks if s.start - 2 <= m.time < s.end]


def write_rpp(path: Path, source: Path, length: float, segments: list[Segment],
              sample_rate: int = 48000) -> None:
    source = source.resolve()
    src_type = SOURCE_TYPES.get(source.suffix.lower(), "VIDEO")  # VIDEO handles m4a/mp4
    lines = [
        '<REAPER_PROJECT 0.1 "7.0/trad-split" 0',
        "  RIPPLE 0",
        "  AUTOXFADE 0",
        f"  SAMPLERATE {sample_rate} 0 0",
    ]
    for i, s in enumerate(segments, 1):
        colour = reaper_colour(SET_RGB if s.kind == SET else CHAT_RGB)
        lines.append(f"  MARKER {i} {s.start:.6f} {_quote(s.name)} 1 {colour}")
        lines.append(f'  MARKER {i} {s.end:.6f} "" 1')
    # Tune changes as plain markers, numbered after the regions.
    n = len(segments)
    for s in segments:
        for m in s.marks:
            n += 1
            lines.append(f"  MARKER {n} {m.time:.6f} {_quote(m.name)} 0")
    lines += [
        "  <TRACK {" + str(uuid.uuid4()).upper() + "}",
        f"    NAME {_quote(source.stem)}",
        "    <ITEM",
        "      POSITION 0",
        f"      LENGTH {length:.6f}",
        "      SOFFS 0",
        f"      NAME {_quote(source.name)}",
        f"      <SOURCE {src_type}",
        f"        FILE {_quote(str(source))}",
        "      >",
        "    >",
        "  >",
        ">",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_TOKEN = re.compile(r'"([^"]*)"|\'([^\']*)\'|`([^`]*)`|(\S+)')


def _tokens(line: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in _TOKEN.finditer(line)]


def read_rpp(path: Path) -> tuple[Path | None, list[Segment]]:
    """Source file and regions (in source-file time) from a saved Reaper project.

    Accounts for the first item's position and start offset, so nudging the
    item on the timeline does not shift the cuts.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    starts: dict[int, tuple[float, str]] = {}
    regions: list[Segment] = []
    marks: list[Mark] = []
    source: Path | None = None
    item_pos = item_offs = None
    in_item = False

    for raw in text.splitlines():
        line = raw.strip()
        tok = _tokens(line)
        if not tok:
            continue
        head = tok[0]
        if head == "MARKER" and len(tok) >= 5:
            idx, pos, name, flags = int(tok[1]), float(tok[2]), tok[3], int(tok[4])
            if not flags & 1:
                marks.append(Mark(pos, name))  # plain marker: a tune change
                continue
            if idx in starts:
                start, rname = starts.pop(idx)
                regions.append(Segment(start, pos, kind_from_name(rname), rname))
            else:
                starts[idx] = (pos, name)
        elif head == "<ITEM" and item_pos is None:
            in_item = True
        elif in_item and head == "POSITION":
            item_pos = float(tok[1])
        elif in_item and head == "SOFFS":
            item_offs = float(tok[1])
        elif in_item and head == "FILE" and source is None:
            source = Path(tok[1])
            if not source.is_absolute():
                source = (path.parent / source).resolve()
            in_item = False

    shift = (item_offs or 0.0) - (item_pos or 0.0)
    for r in regions:
        r.start += shift
        r.end += shift
    for m in marks:
        m.time += shift
    regions.sort(key=lambda r: r.start)
    _attach_marks(regions, marks)
    return source, regions


def write_csv(path: Path, segments: list[Segment]) -> None:
    """Same columns as Reaper's Region/Marker Manager export, so it imports back in."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "Name", "Start", "End", "Length"])
        for i, s in enumerate(segments, 1):
            w.writerow([f"R{i}", s.name, f"{s.start:.3f}", f"{s.end:.3f}", f"{s.duration:.3f}"])
        marks = [m for s in segments for m in s.marks]
        for i, m in enumerate(marks, 1):
            w.writerow([f"M{i}", m.name, f"{m.time:.3f}", "", ""])


def _seconds(value: str) -> float:
    """Accept plain seconds or h:m:s(.fff) / m:s(.fff) as Reaper exports."""
    parts = value.strip().split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def read_csv(path: Path) -> list[Segment]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    segs, marks = [], []
    for row in rows:
        ident = (row.get("#") or "").strip().upper()
        name = (row.get("Name") or "").strip()
        if ident.startswith("M"):
            marks.append(Mark(_seconds(row["Start"]), name))
        elif not ident or ident.startswith("R"):
            segs.append(Segment(_seconds(row["Start"]), _seconds(row["End"]), kind_from_name(name), name))
    segs.sort(key=lambda s: s.start)
    _attach_marks(segs, marks)
    return segs
