"""trad-split command line."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import fields
from pathlib import Path

from . import audio, reaper
from .segment import SET, Segment, SegmentParams, segment

CONFIG_PATH = Path.home() / ".config" / "trad-split" / "config.toml"
MANIFEST = ".trad-split-files"

DEFAULTS = {
    "output": None,  # folder that session folders go in; default is next to each memo
    "vault": None,  # Obsidian vault root, for vault-relative links
    "audio": True,
    "sets_only": False,
    "reaper": True,
    "obsidian": False,
    "plot": False,
    "reencode": False,
    "force": False,
    "rescan": False,
    "device": "auto",
    "model": None,
    "pad": None,  # shortcut for pad_start and pad_end together
    **{f.name: f.default for f in fields(SegmentParams)},
}


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg = {k.replace("-", "_"): v for k, v in cfg.items()}
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        print(f"warning: ignoring unknown config keys in {path}: {', '.join(sorted(unknown))}",
              file=sys.stderr)
    return {k: v for k, v in cfg.items() if k in DEFAULTS}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trad-split",
        description="Split trad session recordings into sets of tunes and the chat in between.",
        epilog=f"Defaults can be set in {CONFIG_PATH}.")
    p.add_argument("inputs", nargs="*", type=Path, help="memo files or folders of memos")
    p.add_argument("-o", "--output", type=Path, help="folder to put session folders in")
    p.add_argument("--config", type=Path, default=CONFIG_PATH, help="config file")

    out = p.add_argument_group("outputs")
    B = argparse.BooleanOptionalAction
    out.add_argument("--audio", action=B, help="export audio files (default on)")
    out.add_argument("--sets-only", action=B, help="export sets only, not chat")
    out.add_argument("--reaper", action=B, help="write Reaper project and regions CSV (default on)")
    out.add_argument("--obsidian", action=B, help="write an Obsidian session note")
    out.add_argument("--vault", type=Path, help="Obsidian vault root, for links")
    out.add_argument("--plot", action=B, help="save a PNG of the scores and segments")
    out.add_argument("--reencode", action=B, help="re-encode to AAC 192k instead of stream copy")
    out.add_argument("--force", action=B, help="overwrite an existing Reaper project or note")

    src = p.add_argument_group("use edited boundaries instead of detecting")
    src.add_argument("--from-reaper", type=Path, metavar="RPP",
                     help="cut the regions in a saved Reaper project (memo taken from the project)")
    src.add_argument("--from-csv", type=Path, metavar="CSV",
                     help="cut the regions in a CSV (give one memo)")

    det = p.add_argument_group("detection tuning")
    det.add_argument("--min-set", type=float, help="shortest set in seconds (default 40)")
    det.add_argument("--min-chat", type=float, help="shortest chat in seconds (default 4)")
    det.add_argument("--pad-start", type=float, help="seconds kept before each set (default 1.5)")
    det.add_argument("--pad-end", type=float,
                     help="seconds kept after each set, keeps the applause (default 3.5)")
    det.add_argument("--pad", type=float, help="set both --pad-start and --pad-end")
    det.add_argument("--switch-penalty", type=float, help="higher = fewer, longer segments (default 12)")
    det.add_argument("--bias", type=float, help="positive favours music, negative chat (default 0)")
    det.add_argument("--rescan", action=B, help="ignore cached model scores")
    det.add_argument("--device", help="torch device: auto, cpu, mps, cuda")
    det.add_argument("--model", type=Path, help="path to Cnn14_DecisionLevelMax checkpoint")
    return p


def resolve_options(args: argparse.Namespace) -> dict:
    cli_values = {k: getattr(args, k, None) for k in DEFAULTS}
    opts = dict(DEFAULTS)
    # Config, then command line; within each, --pad first so the specific pads win.
    for layer in (load_config(args.config), {k: v for k, v in cli_values.items() if v is not None}):
        if layer.get("pad") is not None:
            opts["pad_start"] = opts["pad_end"] = layer["pad"]
        opts.update({k: v for k, v in layer.items() if k != "pad"})
    for key in ("output", "vault", "model"):
        if opts[key] is not None:
            opts[key] = Path(opts[key]).expanduser()
    return opts


def expand_inputs(paths: list[Path]) -> list[Path]:
    memos = []
    for p in paths:
        p = p.expanduser()
        if p.is_dir():
            memos += sorted(f for f in p.iterdir() if f.suffix.lower() in audio.AUDIO_EXTS)
        elif p.exists():
            memos.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return memos


def safe_filename(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "-", name).strip(" .")
    return name or "untitled"


def detect(memo: Path, session_dir: Path, length: float, opts: dict,
           classifier_cache: dict) -> tuple[list[Segment], dict]:
    from . import classify

    cache = session_dir / f"{memo.stem}.scores.npz"
    size = memo.stat().st_size
    scores = None if opts["rescan"] else classify.load_scores(cache, size)
    if scores is None:
        if "clf" not in classifier_cache:
            checkpoint = opts["model"] or classify.CHECKPOINT
            classifier_cache["clf"] = classify.Classifier(checkpoint, opts["device"])
        print("  decoding", file=sys.stderr)
        samples = audio.decode(memo, classify.SAMPLE_RATE)
        scores = classifier_cache["clf"].scores(samples)
        classify.save_scores(cache, scores, size)
    else:
        print("  using cached scores", file=sys.stderr)
    params = SegmentParams(**{f.name: opts[f.name] for f in fields(SegmentParams)})
    return segment(scores["log_odds"], float(scores["hop"]), length, params), scores


def export_audio(memo: Path, session_dir: Path, title: str, segments: list[Segment],
                 opts: dict, recorded) -> dict[int, Path]:
    # Remove what the previous run wrote so renamed regions do not leave stale files.
    manifest = session_dir / MANIFEST
    if manifest.exists():
        for name in manifest.read_text(encoding="utf-8").splitlines():
            (session_dir / name).unlink(missing_ok=True)

    ext = audio.output_ext(memo, opts["reencode"])
    chosen = [(i, s) for i, s in enumerate(segments) if s.kind == SET or not opts["sets_only"]]
    files: dict[int, Path] = {}
    for k, (i, s) in enumerate(chosen, 1):
        dst = session_dir / f"{i + 1:02d} {safe_filename(s.name)}{ext}"
        audio.cut(memo, dst, s.start, s.end, reencode=opts["reencode"], tags={
            "title": s.name, "album": f"{recorded:%Y%m%d} {title}", "artist": "Session",
            "track": f"{k}/{len(chosen)}", "date": f"{recorded:%Y-%m-%d}",
            "comment": f"{s.start:.1f}-{s.end:.1f}s of {memo.name}",
        })
        files[i] = dst
    manifest.write_text("".join(f"{p.name}\n" for p in files.values()), encoding="utf-8")
    return files


def process(memo: Path, opts: dict, *, edited: list[Segment] | None = None,
            session_dir: Path | None = None, classifier_cache: dict | None = None) -> None:
    from .outputs import clock, obsidian_note, plot

    title = memo.stem
    if session_dir is None:
        session_dir = (opts["output"] or memo.parent) / safe_filename(title)
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"{memo.name}", file=sys.stderr)

    length = audio.duration(memo)
    recorded, recorded_from = audio.recorded_at(memo)
    print(f"  recorded {recorded:%Y-%m-%d %H:%M} (from {recorded_from})", file=sys.stderr)
    scores = None
    if edited is None:
        segments, scores = detect(memo, session_dir, length, opts, classifier_cache or {})
    else:
        segments = [s for s in edited if s.end > s.start]

    sets = [s for s in segments if s.kind == SET]
    print(f"  {len(sets)} sets, {clock(sum(s.duration for s in sets))} of music "
          f"in {clock(length)}", file=sys.stderr)
    for s in segments:
        print(f"    {clock(s.start):>8}  {clock(s.end):>8}  {s.name}", file=sys.stderr)

    if opts["reaper"]:
        rpp = session_dir / f"{title}.RPP"
        # Never clobber a project that is the source of this run or may hold edits.
        if edited is None and (opts["force"] or not rpp.exists()):
            reaper.write_rpp(rpp, memo, length, segments)
        elif edited is None:
            print(f"  kept existing {rpp.name} (use --force to replace)", file=sys.stderr)
        reaper.write_csv(session_dir / f"{title}.regions.csv", segments)

    files: dict[int, Path] = {}
    if opts["audio"]:
        files = export_audio(memo, session_dir, title, segments, opts, recorded)

    if opts["obsidian"]:
        note = session_dir / f"{title}.md"
        if opts["force"] or not note.exists():
            note.write_text(obsidian_note(
                title=title, source=memo, recorded=recorded, length=length,
                segments=segments, files=files, link_root=opts["vault"]), encoding="utf-8")
        else:
            print(f"  kept existing {note.name} (use --force to replace)", file=sys.stderr)

    if opts["plot"] and scores is not None:
        plot(session_dir / f"{title}.png", scores, segments, title)

    print(f"  -> {session_dir}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    opts = resolve_options(args)
    try:
        if args.from_reaper:
            rpp = args.from_reaper.expanduser()
            source, regions = reaper.read_rpp(rpp)
            if args.inputs:
                source = args.inputs[0].expanduser()
            if source is None or not source.exists():
                raise SystemExit(f"cannot find the memo referenced by {rpp}; pass it as an argument")
            if not regions:
                raise SystemExit(f"no regions in {rpp}")
            process(source, opts, edited=regions, session_dir=rpp.parent)
            return 0

        memos = expand_inputs(args.inputs)
        if not memos:
            build_parser().print_usage(sys.stderr)
            return 2
        if args.from_csv:
            if len(memos) != 1:
                raise SystemExit("--from-csv needs exactly one memo")
            csv_path = args.from_csv.expanduser()
            process(memos[0], opts, edited=reaper.read_csv(csv_path), session_dir=csv_path.parent)
            return 0

        classifier_cache: dict = {}
        for memo in memos:
            process(memo, opts, classifier_cache=classifier_cache)
        return 0
    except audio.FFmpegMissing as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
