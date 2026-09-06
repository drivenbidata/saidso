"""Writing transcripts to disk.

The markdown shape here is the contract between saidso and whatever reads the
transcript next — an agent, a wiki, or a person six months later. Two rules
hold it together:

* One utterance per line, `[HH:MM:SS] **Speaker:** text`. Line-per-turn means
  grep works, diffs are readable, and a parser needs no state.
* Frontmatter carries everything that isn't dialogue, including how confident
  saidso is about the date. A guess is always labelled as one.

The file is written whole and then moved into place, so a reader — a folder
watcher, a sync job — never sees a half-written transcript.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from .. import __version__
from ..models import Segment, TranscriptMeta, format_timestamp
from . import frontmatter as fm

BLOCK_LISTS = ("participants",)


def _duration_text(meta: TranscriptMeta, segments: list[Segment]) -> str:
    seconds = meta.duration or (segments[-1].end if segments else 0.0)
    return format_timestamp(seconds) if seconds else ""


def speakers_of(segments: list[Segment]) -> list[str]:
    """Unique speakers in order of first appearance."""
    seen: list[str] = []
    for s in segments:
        if s.speaker and s.speaker not in seen:
            seen.append(s.speaker)
    return seen


def build_frontmatter(meta: TranscriptMeta, segments: list[Segment]) -> dict[str, object]:
    data: dict[str, object] = {
        "title": meta.title,
        "date": meta.date,
        "recorded": meta.when,
        "project": meta.project,
        "source": meta.source,
        "duration": _duration_text(meta, segments),
        "language": meta.language or "",
        "speakers": speakers_of(segments),
        "participants": list(meta.participants),
        "link": meta.link,
    }
    if meta.date_inferred:
        # Deliberately adjacent to `date` so anything reading the top of the
        # file sees the caveat at the same time as the value.
        items = list(data.items())
        at = [k for k, _ in items].index("date") + 1
        data = dict(items[:at] + [("date_inferred", True), ("date_source", meta.date_source)] + items[at:])
    data["generator"] = f"saidso {__version__}"
    return data


def render_transcript(segments: list[Segment], meta: TranscriptMeta) -> str:
    """The full markdown document, as text."""
    lines = [fm.dumps(build_frontmatter(meta, segments), block_lists=BLOCK_LISTS), ""]
    lines.append(f"# {meta.title} — Raw Transcript")
    if meta.date_inferred:
        lines.append("")
        lines.append(
            f"*Date {meta.date.isoformat()} was inferred from the {meta.date_source}, "
            "not stated in the recording. Please confirm before relying on it.*"
        )
    lines.append("")

    for seg in segments:
        text = " ".join(seg.text.split())
        if not text:
            continue
        stamp = format_timestamp(seg.start)
        if seg.speaker:
            lines.append(f"[{stamp}] **{seg.speaker}:** {text}")
        else:
            lines.append(f"[{stamp}] {text}")
    lines.append("")
    return "\n".join(lines)


def render_vtt(segments: list[Segment], meta: TranscriptMeta) -> str:
    """WebVTT, for tools that want cues and timing rather than prose."""
    lines = [
        "WEBVTT",
        f"NOTE {meta.title} — {meta.when:%Y-%m-%d %H:%M} — source: {meta.source}",
        "",
    ]
    for i, seg in enumerate(segments, 1):
        text = " ".join(seg.text.split())
        if not text:
            continue
        lines.append(str(i))
        lines.append(
            f"{format_timestamp(seg.start, millis=True)} --> {format_timestamp(seg.end, millis=True)}"
        )
        lines.append(f"<v {seg.speaker}>{text}</v>" if seg.speaker else text)
        lines.append("")
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> Path:
    """Write via a temp file in the same directory, then replace.

    Same directory so the replace is a rename on one filesystem, which is what
    makes it atomic. A watcher polling the inbox must never pick up a transcript
    that is still being written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def write_transcript(segments: list[Segment], path: Path, meta: TranscriptMeta) -> Path:
    return write_atomic(Path(path), render_transcript(segments, meta))


def write_vtt(segments: list[Segment], path: Path, meta: TranscriptMeta) -> Path:
    return write_atomic(Path(path), render_vtt(segments, meta))


def read_meta(path: Path) -> dict[str, object]:
    """Frontmatter of an existing transcript, or {}."""
    try:
        return fm.loads(Path(path).read_text(encoding="utf-8", errors="replace")[:8192])
    except OSError:
        return {}


def now() -> dt.datetime:
    return dt.datetime.now()
