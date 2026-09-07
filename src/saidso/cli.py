"""The `saidso` command line.

Every capability is reachable here, and the desktop shell drives the same
functions rather than reimplementing them — so anything you can do in the
window you can script, and anything that works in a script works in the window.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import sys
import time
from pathlib import Path

from . import __version__, paths
from . import config as config_mod
from .errors import SaidsoError
from .parse import SUPPORTED_SUFFIXES as TRANSCRIPT_SUFFIXES
from .transcribe import MODELS, is_media

EPILOG = """\
examples:
  saidso init                                  set up config and the notes folder
  saidso devices                               list microphones and system-audio inputs
  saidso record --name "Weekly Sync"           record a meeting, transcribe on stop
  saidso transcribe meeting.mp4                transcribe a recording file
  saidso ingest teams-export.vtt               file an existing transcript
  saidso watch ~/Downloads/recordings          transcribe anything dropped in a folder
  saidso parse transcript.vtt                  print a clean Speaker: text log
  saidso tracker sweep                         move ticked items into Completed
  saidso sync                                  pull, stage, guard, commit, push
"""


# ---------------------------------------------------------------- helpers


def _out(msg: str = "") -> None:
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _load(args: argparse.Namespace):
    cfg = config_mod.load(Path(args.config) if args.config else None)
    if getattr(args, "notes_dir", None):
        from dataclasses import replace

        cfg = replace(cfg, notes_dir=Path(args.notes_dir).expanduser())
    return cfg


def _progress(quiet: bool):
    """A terminal progress reporter that stays on one line."""
    if quiet:
        return None
    state = {"last": 0.0, "msg": ""}

    def report(fraction: float | None, message: str) -> None:
        now = time.time()
        if fraction is not None and now - state["last"] < 0.25 and fraction < 1.0:
            return
        state["last"] = now
        if fraction is None:
            line = f"  {message}..."
        else:
            done = int(fraction * 24)
            line = f"  [{'#' * done}{'.' * (24 - done)}] {fraction * 100:5.1f}%  {message}"
        pad = max(0, len(state["msg"]) - len(line))
        state["msg"] = line
        print("\r" + line + " " * pad, end="", file=sys.stderr, flush=True)

    return report


def _finish_progress(quiet: bool) -> None:
    if not quiet:
        print("", file=sys.stderr, flush=True)


def _report(outcome, cfg) -> None:
    rel = outcome.transcript
    # A transcript written outside the notes directory keeps its absolute path.
    with contextlib.suppress(ValueError):
        rel = outcome.transcript.relative_to(cfg.notes_dir)
    unit = "turns" if outcome.kind == "ingested" else "segments"
    _out(f"  -> {rel}  ({outcome.segments} {unit}, project: {outcome.project})")
    if outcome.vtt:
        _out(f"     also wrote {outcome.vtt.name}")
    for note in outcome.notes:
        _out(f"     note: {note}")
    for kept in outcome.audio_kept:
        _out(f"     audio kept: {kept}")


# ---------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.config) if args.config else paths.config_file()
    if target.exists() and not args.force:
        cfg = config_mod.load(target)
        _out(f"Config already exists: {target}")
        _out(f"Notes directory:       {cfg.notes_dir}")
        _out("Pass --force to overwrite it.")
        return 0

    notes = Path(args.notes_dir).expanduser() if args.notes_dir else paths.default_notes_dir()
    cfg = config_mod.starter(notes_dir=notes, speaker_name=args.name or "")
    cfg.save(target)

    for folder in (cfg.inbox_dir, cfg.processed_dir, cfg.project_dir()):
        folder.mkdir(parents=True, exist_ok=True)

    _out(f"Wrote {target}")
    _out(f"Notes directory: {cfg.notes_dir}")
    _out("")
    _out("Next:")
    if not cfg.speaker_name:
        _out("  * set identity.name in the config — it becomes your speaker tag")
    _out("  * saidso devices        check your microphone and system audio")
    _out("  * saidso record         record your first meeting")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    from .capture import LOOPBACK, MIC, available_backends, get_backend
    from .errors import CaptureUnavailable

    cfg = _load(args)
    try:
        backend = get_backend(cfg.capture.backend)
    except CaptureUnavailable as e:
        _err(str(e))
        return 1

    _out(f"Capture backend: {backend.id}  (available: {', '.join(b.id for b in available_backends())})")
    for kind, heading in ((MIC, "Microphones"), (LOOPBACK, "System audio (loopback)")):
        _out("")
        _out(f"{heading}:")
        found = [d for d in backend.devices() if d.kind == kind]
        if not found:
            _out("  (none)")
        for d in found:
            _out(f"  {d}")
    backend.close()
    _out("")
    _out("Set capture.mic / capture.system in the config to a name fragment or index.")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from .pipeline import LiveSession

    cfg = _load(args)
    session = LiveSession(
        cfg,
        title=args.name,
        project=args.project,
        link=args.link or "",
        participants=_participants(args.participants),
        model=args.model,
        diarize_audio=True if args.diarize else (False if args.no_diarize else None),
    )
    _out(f"Recording '{session.title}' -> project {session.route.project.key}")
    _out(f"  microphone:   {session.mic or '(none)'}")
    _out(f"  system audio: {session.system or '(none)'}")
    _out("")
    _out("Press Enter to stop and transcribe (Ctrl+C to discard).")
    session.start()
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        _out("")
        _out("Discarded.")
        session.cancel()
        return 130

    _out(f"Stopped after {int(session.elapsed // 60)}m {int(session.elapsed % 60)}s. Transcribing...")
    outcome = session.stop(progress=_progress(args.quiet))
    _finish_progress(args.quiet)
    _report(outcome, cfg)
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    from .pipeline import transcribe_file

    cfg = _load(args)
    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            targets += sorted(p for p in path.iterdir() if is_media(p))
        elif path.exists():
            targets.append(path)
        else:
            _err(f"Not found: {path}")

    if not targets:
        _err("Nothing to transcribe.")
        return 1

    failures = 0
    for path in targets:
        _out(f"{path.name}")
        try:
            outcome = transcribe_file(
                cfg,
                path,
                project=args.project,
                title=args.title,
                model=args.model,
                diarize_audio=True if args.diarize else (False if args.no_diarize else None),
                link=args.link or "",
                participants=_participants(args.participants),
                progress=_progress(args.quiet),
            )
            _finish_progress(args.quiet)
            _report(outcome, cfg)
        except SaidsoError as e:
            _finish_progress(args.quiet)
            _err(f"  failed: {e}")
            failures += 1
    return 1 if failures else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from .pipeline import ingest_file

    cfg = _load(args)
    targets: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            targets += sorted(p for p in path.iterdir() if p.suffix.lower() in TRANSCRIPT_SUFFIXES)
        elif path.exists():
            targets.append(path)
        else:
            _err(f"Not found: {path}")

    if not targets:
        _err("Nothing to ingest.")
        return 1

    when = dt.datetime.fromisoformat(args.date) if args.date else None
    failures = 0
    for path in targets:
        _out(f"{path.name}")
        try:
            _report(
                ingest_file(
                    cfg, path, project=args.project, title=args.title, when=when,
                    link=args.link or "", participants=_participants(args.participants),
                ),
                cfg,
            )
        except SaidsoError as e:
            _err(f"  failed: {e}")
            failures += 1
    return 1 if failures else 0


def cmd_watch(args: argparse.Namespace) -> int:
    from .pipeline import transcribe_file

    cfg = _load(args)
    folder = Path(args.folder).expanduser() if args.folder else cfg.recordings_dir
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "done"
    done.mkdir(exist_ok=True)

    _out(f"Watching {folder} — drop recordings there. Ctrl+C to stop.")
    _out(f"Transcripts go to {cfg.inbox_dir}; handled recordings move to {done.name}/.")
    try:
        while True:
            for path in sorted(folder.iterdir()):
                if path.is_dir() or not is_media(path):
                    continue
                if not _stable(path):
                    continue
                _out(f"{path.name}")
                try:
                    outcome = transcribe_file(cfg, path, project=args.project,
                                              progress=_progress(args.quiet))
                    _finish_progress(args.quiet)
                    _report(outcome, cfg)
                    _move_aside(path, done)
                except SaidsoError as e:
                    _finish_progress(args.quiet)
                    _err(f"  failed: {e}")
                except OSError as e:
                    _err(f"  skipped {path.name}: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        _out("")
        _out("Stopped.")
        return 0


def cmd_parse(args: argparse.Namespace) -> int:
    from .parse import parse_file

    result = parse_file(Path(args.path))
    if args.speakers:
        for name in result.speakers:
            _out(name)
        return 0
    _out(result.as_log())
    if not result.attributed:
        _err("note: this transcript had no speaker structure — nothing can be attributed.")
    else:
        _err(f"speakers: {', '.join(result.speakers)}")
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not cfg.projects:
        _out("No projects configured.")
        return 0
    width = max(len(p.key) for p in cfg.projects)
    for p in cfg.projects:
        mark = "*" if p.key == cfg.default_project else " "
        state = "" if p.active else "  (inactive)"
        _out(f" {mark} {p.key:<{width}}  {p.label}  ->  {p.folder}/{state}")
    _out("")
    _out(f"* = default. Edit {cfg.source_path} to add or retire a project.")
    return 0


def cmd_tracker(args: argparse.Namespace) -> int:
    from . import tracker

    cfg = _load(args)
    if args.tracker_cmd == "add":
        path = tracker.add_to_project(
            cfg, args.project, heading=args.heading, items=args.item,
            date=dt.date.fromisoformat(args.date) if args.date else None,
        )
        _out(f"Added {len(args.item)} item(s) to {path}")
        return 0

    report = tracker.sweep_all(cfg, dry_run=args.dry_run)
    for key, result in report.swept.items():
        if result.moved:
            verb = "would move" if args.dry_run else "moved"
            _out(f"{key}: {verb} {len(result.moved)} item(s) to Completed")
            for text in result.moved:
                _out(f"    {text}")
        for heading in result.dropped_headings:
            _out(f"    dropped finished meeting {heading.lstrip('# ')}")
    if not report.moved:
        _out("Nothing ticked — no items to move.")
    if report.index_path:
        _out(f"Index rebuilt: {report.index_path}")
    for problem in report.problems:
        _err(f"REFUSED {problem}")
    return 1 if report.problems else 0


def cmd_sync(args: argparse.Namespace) -> int:
    from .sync import sync

    cfg = _load(args)
    result = sync(cfg, message=args.message, push=not args.no_push, dry_run=args.dry_run)
    for line in result.log:
        _out(f"  {line}")
    if result.refused:
        _err(result.refused)
        return 1
    if result.committed:
        _out(f"Committed: {result.message}")
    if result.pushed:
        _out("Pushed.")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    target = Path(args.config) if args.config else paths.config_file()
    if args.config_cmd == "path":
        _out(str(target))
        return 0
    if not target.exists():
        _err(f"No config at {target}. Run: saidso init")
        return 1
    _out(target.read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------- utilities


def _participants(raw: str | None) -> list[str]:
    import re

    return [p.strip() for p in re.split(r"[;,\n]+", raw or "") if p.strip()]


def _stable(path: Path, wait: float = 2.0) -> bool:
    """True when a file has stopped growing — it may still be copying."""
    try:
        first = path.stat().st_size
        time.sleep(wait)
        return path.stat().st_size == first
    except OSError:
        return False


def _move_aside(path: Path, done: Path) -> None:
    target = done / path.name
    n = 2
    while target.exists():
        target = done / f"{path.stem}-{n}{path.suffix}"
        n += 1
    path.rename(target)


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saidso",
        description="Record, transcribe and organise meetings on your own machine.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"saidso {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="FILE", help="config file to use")
    common.add_argument("--notes-dir", metavar="DIR", help="override the notes directory")
    common.add_argument("-q", "--quiet", action="store_true", help="no progress output")

    media = argparse.ArgumentParser(add_help=False)
    media.add_argument("--project", metavar="KEY", help="file the transcript under this project")
    media.add_argument("--model", choices=MODELS, help="Whisper model size")
    media.add_argument("--diarize", action="store_true", help="label individual speakers")
    media.add_argument("--no-diarize", action="store_true", help="don't label individual speakers")
    media.add_argument("--link", metavar="URL", help="meeting link, recorded in the frontmatter")
    media.add_argument("--participants", metavar="LIST", help="names or emails, comma separated")

    sub = parser.add_subparsers(dest="command", required=True)

    # --notes-dir comes from `common`; for init it means "create it here".
    p = sub.add_parser("init", parents=[common], help="create the config and notes folder")
    p.add_argument("--name", metavar="NAME", help="your full name, used as your speaker tag")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("devices", parents=[common], help="list audio inputs")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("record", parents=[common, media], help="record a meeting live")
    p.add_argument("--name", metavar="TITLE", help="meeting name")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("transcribe", parents=[common, media], help="transcribe recording file(s)")
    p.add_argument("paths", nargs="+", metavar="PATH", help="files or folders")
    p.add_argument("--title", metavar="TITLE", help="meeting title (defaults to the filename)")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser(
        "ingest", parents=[common], help="bring an existing transcript into the inbox"
    )
    p.add_argument("paths", nargs="+", metavar="PATH", help=".vtt, .docx, .md or .txt, or folders")
    p.add_argument("--project", metavar="KEY", help="file it under this project")
    p.add_argument("--title", metavar="TITLE", help="meeting title (defaults to the filename)")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="the meeting date, if the file lacks one")
    p.add_argument("--link", metavar="URL", help="meeting link, recorded in the frontmatter")
    p.add_argument("--participants", metavar="LIST", help="names or emails, comma separated")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("watch", parents=[common], help="transcribe anything dropped in a folder")
    p.add_argument("folder", nargs="?", metavar="DIR", help="folder to watch")
    p.add_argument("--project", metavar="KEY", help="file transcripts under this project")
    p.add_argument("--interval", type=float, default=5.0, metavar="SEC", help="poll interval")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("parse", help="print a clean Speaker: text log from any transcript")
    p.add_argument("path", metavar="FILE", help=".vtt, .docx, .md or .txt")
    p.add_argument("--speakers", action="store_true", help="print only the speaker list")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("projects", parents=[common], help="list configured projects")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("tracker", parents=[common], help="action tracker maintenance")
    tsub = p.add_subparsers(dest="tracker_cmd", required=True)
    ts = tsub.add_parser("sweep", parents=[common], help="move ticked items into Completed")
    ts.add_argument("--dry-run", action="store_true", help="report without writing")
    ts.set_defaults(func=cmd_tracker)
    ta = tsub.add_parser("add", parents=[common], help="add items to a project's tracker")
    ta.add_argument("--project", required=True, metavar="KEY")
    ta.add_argument("--heading", required=True, metavar="TEXT", help="meeting heading")
    ta.add_argument("--item", action="append", required=True, metavar="TEXT", help="repeatable")
    ta.add_argument("--date", metavar="YYYY-MM-DD")
    ta.set_defaults(func=cmd_tracker)

    p = sub.add_parser("sync", parents=[common], help="mirror the notes directory with git")
    p.add_argument("-m", "--message", metavar="MSG", help="commit message")
    p.add_argument("--no-push", action="store_true", help="commit but don't push")
    p.add_argument("--dry-run", action="store_true", help="report without committing")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("config", parents=[common], help="show the config or its location")
    csub = p.add_subparsers(dest="config_cmd", required=True)
    for name, helptext in (("show", "print the config"), ("path", "print the config path")):
        cp = csub.add_parser(name, parents=[common], help=helptext)
        cp.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SaidsoError as e:
        _err(f"saidso: {e}")
        return 2
    except KeyboardInterrupt:
        _err("")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
