"""ffmpeg/ffprobe helpers: decode, probe, cut."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aif", ".aiff", ".flac", ".ogg", ".opus", ".caf", ".mp4"}


class FFmpegMissing(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
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


def recorded_at(path: Path) -> datetime:
    """Recording time from the file's creation_time tag, else its modification time.

    Voice Memos stores creation_time in UTC; convert to local time.
    """
    try:
        tags = probe(path)["format"].get("tags", {})
        stamp = tags.get("creation_time") or tags.get("date")
        if stamp:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (subprocess.CalledProcessError, ValueError, KeyError):
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def output_ext(src: Path, reencode: bool) -> str:
    if reencode:
        return ".m4a"
    ext = src.suffix.lower()
    # Stream copy into the same container type; .caf and .mp4 audio go to .m4a.
    return ".m4a" if ext in {".caf", ".mp4"} else ext


def cut(src: Path, dst: Path, start: float, end: float, *, reencode: bool = False,
        tags: dict[str, str] | None = None) -> None:
    """Write src[start:end] to dst. Stream copy by default (fast, no quality loss)."""
    cmd = [_tool("ffmpeg"), "-nostdin", "-v", "error", "-y",
           "-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.01):.3f}", "-i", str(src),
           "-vn", "-map_metadata", "-1"]
    if reencode:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c", "copy"]
    for key, value in (tags or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    if dst.suffix.lower() == ".m4a":
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    subprocess.run(cmd, check=True, capture_output=True)
