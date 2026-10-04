"""Obsidian session note and diagnostic plot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from .segment import SET, Segment
from .tunes import TAIL


def clock(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def loop_time(seconds: float) -> str:
    """m:ss or m:ss.s, the format the audio-loop-player plugin reads."""
    tenths = int(round(max(seconds, 0) * 10))
    m, rest = divmod(tenths, 600)
    s, t = divmod(rest, 10)
    return f"{m}:{s:02d}" + (f".{t}" if t else "")


def parse_loop_time(text: str) -> float:
    """Inverse of loop_time: 'm:ss', 'm:ss.s' (or plain seconds) to seconds."""
    total = 0.0
    for part in text.strip().split(":"):
        total = total * 60 + float(part)
    return total


def loops_block(file_link: str, segment: Segment, tail: float = TAIL) -> list[str]:
    """Tune sections for the audio-loop-player plugin, times relative to the set file.

    Each tune but the last runs `tail` seconds past the change into the next,
    since changes are found a little early and would clip its last notes.
    """
    lines = ["```loops", f"file: {file_link}"]
    for a, b, name in segment.tunes():
        if b < segment.end:
            b = min(b + tail, segment.end)
        lines.append(f"{loop_time(a - segment.start)} - {loop_time(b - segment.start)} | {name}")
    return lines + ["```"]


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def obsidian_note(*, title: str, source: Path, recorded: datetime, length: float,
                  segments: list[Segment], files: dict[int, Path],
                  link_root: Path | None, tail: float = TAIL) -> str:
    """Markdown with YAML frontmatter and one section per set.

    files maps segment index to the exported audio file. Links are relative to
    link_root (the vault) when given, otherwise bare file names.
    """
    def link(p: Path) -> str:
        if link_root is not None:
            try:
                return p.resolve().relative_to(link_root.resolve()).as_posix()
            except ValueError:
                pass
        return p.name

    sets = [(i, s) for i, s in enumerate(segments) if s.kind == SET]
    lines = [
        "---",
        "type: session",
        f"date: {recorded:%Y-%m-%d}",
        f"time: {_yaml_str(f'{recorded:%H:%M}')}",
        f"source: {_yaml_str(source.name)}",
        f"duration: {_yaml_str(clock(length))}",
        f"set_count: {len(sets)}",
        f"music_minutes: {round(sum(s.duration for _, s in sets) / 60, 1)}",
        "location:",
        "players: []",
        "tags: [session]",
        "---",
        "",
        f"# {title}",
        "",
    ]
    for i, s in sets:
        lines += [
            f"## {s.name}",
            f"{clock(s.start)} to {clock(s.end)} ({clock(s.duration)})",
            "",
        ]
        if i in files:
            lines += [f"![[{link(files[i])}]]", *loops_block(link(files[i]), s, tail), ""]
        elif len(s.tunes()) > 1:
            lines += [f"- {clock(a)} {name}" for a, _, name in s.tunes()] + [""]
        lines += ["tunes:: ", "notes:: ", ""]

    lines += ["## Timeline", "", "| # | Segment | Start | End | Length |", "|---|---|---|---|---|"]
    for n, s in enumerate(segments, 1):
        name = f"[[{link(files[n - 1])}\\|{s.name}]]" if (n - 1) in files else s.name
        lines.append(f"| {n} | {name} | {clock(s.start)} | {clock(s.end)} | {clock(s.duration)} |")
    return "\n".join(lines) + "\n"


def plot(path: Path, scores: dict[str, np.ndarray], segments: list[Segment], title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hop = float(scores["hop"])
    t = np.arange(len(scores["log_odds"])) * hop / 60
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})
    ax1.plot(t, scores["music"], lw=0.7, label="music")
    ax1.plot(t, scores["chat"], lw=0.7, label="chat")
    ax1.set_ylabel("probability")
    ax1.set_ylim(0, 1)
    ax1.legend(loc="upper right")
    ax1.set_title(title)
    ax2.plot(t, scores["log_odds"], lw=0.5, color="0.3")
    ax2.axhline(0, color="0.6", lw=0.5)
    ax2.set_ylabel("log-odds (music > 0)")
    ax2.set_xlabel("minutes")
    for s in segments:
        colour = "tab:green" if s.kind == SET else "tab:gray"
        for ax in (ax1, ax2):
            ax.axvspan(s.start / 60, s.end / 60, color=colour, alpha=0.15, lw=0)
            for m in s.marks:
                ax.axvline(m.time / 60, color="tab:green", ls="--", lw=0.8)
        if s.kind == SET:
            ax1.text((s.start + s.end) / 120, 0.95, s.name, ha="center", va="top", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
