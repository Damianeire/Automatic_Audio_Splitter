"""Music vs chat scoring with the PANNs Cnn14_DecisionLevelMax sound event model.

The model gives 527 AudioSet class probabilities at 100 frames per second.
We pool those to HOP-second frames and reduce them to one number per frame:
log(music) - log(chat).
"""

from __future__ import annotations

import csv
import sys
import urllib.request
from pathlib import Path

import numpy as np

SAMPLE_RATE = 32000
MODEL_FPS = 100  # PANNs hop of 320 samples at 32 kHz
HOP = 0.5  # seconds per scored frame
CHUNK = 60.0  # seconds of audio per model call, keeps memory flat on long memos
CONTEXT = 5.0  # extra audio either side of each chunk, discarded after inference

PANNS_DIR = Path.home() / "panns_data"
CHECKPOINT = PANNS_DIR / "Cnn14_DecisionLevelMax.pth"
LABELS_CSV = PANNS_DIR / "class_labels_indices.csv"
CHECKPOINT_URL = "https://zenodo.org/records/3987831/files/Cnn14_DecisionLevelMax_mAP%3D0.385.pth?download=1"
LABELS_URL = "https://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv"
CHECKPOINT_MIN_BYTES = 300_000_000

# Anything that says "someone is playing". Singing counts: a song is a set.
MUSIC_CLASSES = [
    "Music", "Musical instrument", "Folk music", "Traditional music",
    "Bowed string instrument", "Violin, fiddle",
    "Plucked string instrument", "Guitar", "Acoustic guitar", "Banjo", "Mandolin",
    "Wind instrument, woodwind instrument", "Flute", "Whistle", "Harmonica",
    "Accordion", "Bagpipes", "Piano", "Drum", "Singing",
]
# Anything that says "people talking, not playing".
CHAT_CLASSES = [
    "Speech", "Male speech, man speaking", "Female speech, woman speaking",
    "Conversation", "Narration, monologue", "Babbling", "Laughter",
    "Chatter", "Crowd", "Hubbub, speech noise, speech babble",
    "Clapping", "Cheering",
]
EPS = 1e-3


def _download(url: str, dest: Path, what: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"Downloading {what} (one-off) to {dest}", file=sys.stderr)

    def progress(blocks: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            print(f"\r  {pct:3d}%", end="", file=sys.stderr)

    urllib.request.urlretrieve(url, tmp, reporthook=progress)
    print(file=sys.stderr)
    tmp.replace(dest)


def ensure_model_files(checkpoint: Path = CHECKPOINT) -> None:
    # panns_inference fetches these with wget at import time, which macOS lacks,
    # so get them first with urllib.
    if not LABELS_CSV.exists():
        _download(LABELS_URL, LABELS_CSV, "AudioSet labels")
    if not checkpoint.exists() or checkpoint.stat().st_size < CHECKPOINT_MIN_BYTES:
        _download(CHECKPOINT_URL, checkpoint, "PANNs model, about 320 MB")


def load_labels() -> list[str]:
    with open(LABELS_CSV, newline="") as f:
        rows = list(csv.reader(f))
    return [r[2] for r in rows[1:]]


def class_indices(labels: list[str], names: list[str]) -> list[int]:
    missing = [n for n in names if n not in labels]
    if missing:
        raise ValueError(f"Unknown AudioSet classes: {missing}")
    return [labels.index(n) for n in names]


def pick_device(requested: str = "auto") -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Classifier:
    def __init__(self, checkpoint: Path = CHECKPOINT, device: str = "auto"):
        ensure_model_files(checkpoint)
        import torch
        from panns_inference.models import Cnn14_DecisionLevelMax

        self.torch = torch
        self.device = pick_device(device)
        self.model = Cnn14_DecisionLevelMax(
            sample_rate=SAMPLE_RATE, window_size=1024, hop_size=320, mel_bins=64,
            fmin=50, fmax=14000, classes_num=527, interpolate_mode="nearest")
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.model.load_state_dict(state["model"])
        self.model.to(self.device).eval()
        labels = load_labels()
        self.music_ix = class_indices(labels, MUSIC_CLASSES)
        self.chat_ix = class_indices(labels, CHAT_CLASSES)

    def framewise(self, audio: np.ndarray) -> np.ndarray:
        """(frames, 527) probabilities at MODEL_FPS for the whole recording."""
        n_frames = len(audio) * MODEL_FPS // SAMPLE_RATE
        out = np.zeros((n_frames, 527), dtype=np.float32)
        chunk, ctx = int(CHUNK * SAMPLE_RATE), int(CONTEXT * SAMPLE_RATE)
        spf = SAMPLE_RATE // MODEL_FPS
        total_chunks = max(1, -(-len(audio) // chunk))
        for k, start in enumerate(range(0, len(audio), chunk)):
            print(f"\r  analysing {k + 1}/{total_chunks}", end="", file=sys.stderr)
            a, b = max(0, start - ctx), min(len(audio), start + chunk + ctx)
            piece = audio[a:b]
            if len(piece) < SAMPLE_RATE:  # the model needs at least ~1 s
                piece = np.pad(piece, (0, SAMPLE_RATE - len(piece)))
            with self.torch.no_grad():
                x = self.torch.from_numpy(piece[None, :]).to(self.device)
                fw = self.model(x, None)["framewise_output"][0].cpu().numpy()
            # Keep only the frames belonging to [start, start + chunk).
            f0 = start // spf
            f1 = min(n_frames, (start + chunk) // spf)
            off = f0 - a // spf
            take = fw[off:off + (f1 - f0)]
            out[f0:f0 + len(take)] = take
        print(file=sys.stderr)
        return out

    def scores(self, audio: np.ndarray) -> dict[str, np.ndarray]:
        return pool_scores(self.framewise(audio), self.music_ix, self.chat_ix)


def pool_scores(framewise: np.ndarray, music_ix: list[int], chat_ix: list[int],
                hop: float = HOP) -> dict[str, np.ndarray]:
    """Average to hop-second frames and reduce to music, chat and log-odds."""
    per = int(round(hop * MODEL_FPS))
    n = int(np.ceil(len(framewise) / per))
    padded = np.pad(framewise, ((0, n * per - len(framewise)), (0, 0)), mode="edge")
    pooled = padded.reshape(n, per, -1).mean(axis=1)
    music = pooled[:, music_ix].max(axis=1)
    chat = pooled[:, chat_ix].max(axis=1)
    log_odds = np.log(music + EPS) - np.log(chat + EPS)
    return {"music": music, "chat": chat, "log_odds": log_odds, "hop": np.float32(hop)}


def save_scores(path: Path, scores: dict[str, np.ndarray], source_size: int) -> None:
    np.savez_compressed(path, source_size=source_size, **scores)


def load_scores(path: Path, source_size: int) -> dict[str, np.ndarray] | None:
    """Cached scores, or None if missing or made from a different file."""
    if not path.exists():
        return None
    data = dict(np.load(path))
    if int(data.pop("source_size", -1)) != source_size:
        return None
    return data
