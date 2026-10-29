"""ffmpeg/ffprobe helpers: decode, probe, cut."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aif", ".aiff", ".flac", ".ogg", ".opus", ".caf", ".mp4"}


class FFmpegMissing(RuntimeError):
    pass


def _tool(name: str) -> str:
    # Apps like Obsidian run commands with a bare PATH, so also look where Homebrew installs.
    path = shutil.which(name) or shutil.which(name, path="/opt/homebrew/bin:/usr/local/bin")
    if not path:
        raise FFmpegMissing(f"{name} not found. Install it with: brew install ffmpeg")
    return path


def decode(path: Path, sample_rate: int = 32000) -> np.ndarray:
    """Decode any audio file to mono float32 at sample_rate."""
    cmd = [_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def probe(path: Path) -> dict:
    cmd = [_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True).stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def _parse_stamp(stamp: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # Tags are UTC (or carry their own offset); naive ones are taken as local.
    when = when.astimezone().replace(tzinfo=None)
    return when if when.year >= 2000 else None  # ignore zeroed 1904/1970 stamps


def recorded_at(path: Path) -> tuple[datetime, str]:
    """When the memo was recorded, and where that came from.

    Prefers the creation_time tag Voice Memos writes into the file, then the
    file's creation date on disk (macOS keeps this through copies better than
    the modified date), then the modified date.
    """
    try:
        info = probe(path)
        for tags in [info["format"].get("tags", {})] + [s.get("tags", {}) for s in info.get("streams", [])]:
            for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
                if tags.get(key) and (when := _parse_stamp(tags[key])):
                    return when, "file metadata"
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
        pass
    st = path.stat()
    if getattr(st, "st_birthtime", 0):
        return datetime.fromtimestamp(st.st_birthtime), "file created date"
    return datetime.fromtimestamp(st.st_mtime), "file modified date"


def output_ext(src: Path, reencode: bool) -> str:
    if reencode:
        return ".m4a"
    ext = src.suffix.lower()
    # Stream copy into the same container type; .caf and .mp4 audio go to .m4a.
    return ".m4a" if ext in {".caf", ".mp4"} else ext


CHAPTER_EXTS = {".m4a", ".mp3", ".mp4"}


def _ffmetadata(chapters: list[tuple[float, float, str]]) -> str:
    def esc(s: str) -> str:
        return "".join("\\" + c if c in "=;#\\\n" else c for c in s)

    lines = [";FFMETADATA1"]
    for a, b, title in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(a * 1000)}", f"END={round(b * 1000)}",
                  f"title={esc(title)}"]
    return "\n".join(lines) + "\n"


def codec_for(src: Path, dst: Path) -> str:
    """Stream copy when the container matches, otherwise encode to dst's format."""
    same = {".m4a", ".mp4", ".caf"}
    s, d = src.suffix.lower(), dst.suffix.lower()
    if s == d or (s in same and d in same):
        return "copy"
    return {".mp3": "mp3", ".m4a": "aac"}.get(d, "copy")


class _ChapterFile:
    """A temporary ffmetadata file of chapters, as extra ffmpeg input arguments."""

    def __init__(self, chapters: list[tuple[float, float, str]]):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        f.write(_ffmetadata(chapters))
        f.close()
        self.path = Path(f.name)

    def input_args(self) -> list[str]:
        return ["-f", "ffmetadata", "-i", str(self.path)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


MP3_ARGS = ["-c:a", "libmp3lame", "-q:a", "2", "-id3v2_version", "3"]


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        if "libmp3lame" in result.stderr:
            raise FFmpegMissing("this ffmpeg cannot write mp3. Install one that can: brew install ffmpeg")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)


def cut(src: Path, dst: Path, start: float, end: float, *, reencode: bool = False,
        codec: str | None = None, tags: dict[str, str] | None = None,
        chapters: list[tuple[float, float, str]] | None = None) -> None:
    """Write src[start:end] to dst.

    codec is "copy" (fast, no quality loss), "aac" or "mp3"; reencode=True is
    the older way of asking for "aac". chapters are (start, end, title) in
    seconds from the start of dst, embedded where the format supports them.
    """
    codec = codec or ("aac" if reencode else "copy")
    cmd = [_tool("ffmpeg"), "-nostdin", "-v", "error", "-y",
           "-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.01):.3f}", "-i", str(src)]
    meta_file = None
    if chapters and len(chapters) > 1 and dst.suffix.lower() in CHAPTER_EXTS:
        meta_file = _ChapterFile(chapters)
        # Metadata from the chapter file (it has no global tags), so chapter titles survive.
        cmd += [*meta_file.input_args(), "-map", "0:a", "-map_chapters", "1", "-map_metadata", "1"]
    else:
        cmd += ["-map_metadata", "-1"]
    cmd += ["-vn"]
    if codec == "aac":
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    elif codec == "mp3":
        cmd += MP3_ARGS
    else:
        cmd += ["-c", "copy"]
    for key, value in (tags or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    if dst.suffix.lower() == ".m4a":
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    try:
        _run(cmd)
    finally:
        if meta_file:
            meta_file.path.unlink(missing_ok=True)


def join(src: Path, dst: Path, spans: list[tuple[float, float]], *,
         tags: dict[str, str] | None = None, titles: list[str] | None = None,
         fade: float = 0.5) -> float:
    """Write the spans of src back to back into one mp3 at dst; return its length.

    Each span fades in and out over `fade` seconds so the joins don't click.
    titles, one per span, become chapters.
    """
    parts, offsets, t = [], [], 0.0
    for n, (a, b) in enumerate(spans):
        length = b - a
        f = min(fade, length / 2)
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={f:.3f},afade=t=out:st={length - f:.3f}:d={f:.3f}[s{n}]")
        offsets.append((t, t + length))
        t += length
    graph = ";".join(parts) + ";" + "".join(f"[s{n}]" for n in range(len(spans))) + \
        f"concat=n={len(spans)}:v=0:a=1[out]"
    cmd = [_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(src)]
    with _ChapterFile([(a, b, name) for (a, b), name in zip(offsets, titles or [])]) as meta:
        if titles:
            cmd += [*meta.input_args(), "-map_chapters", "1", "-map_metadata", "1"]
        else:
            cmd += ["-map_metadata", "-1"]
        cmd += ["-filter_complex", graph, "-map", "[out]", *MP3_ARGS]
        for key, value in (tags or {}).items():
            cmd += ["-metadata", f"{key}={value}"]
        cmd.append(str(dst))
        _run(cmd)
    return t
