"""Per-format transcript readers.

Each returns a flat list of Utterance. Timing is discarded here on purpose:
downstream synthesis reads content, and timestamps are noise once the meeting
date is known. Anything that needs timing works from Segments instead, upstream
of this module.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import MissingDependency
from ..models import Utterance
from . import patterns as P


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block if present."""
    lead = text.lstrip()
    if lead.startswith("---"):
        m = P.FRONTMATTER_RE.match(lead)
        if m:
            return lead[m.end():]
    return text


def plausible_speaker(name: str) -> bool:
    """Filter out section labels and URLs masquerading as speaker names."""
    n = name.strip().lower()
    if n in P.NOT_SPEAKERS:
        return False
    if len(name) > 48:
        return False
    # A name doesn't contain sentence punctuation followed by a space.
    return not re.search(r"[.!?,;]\s", name)


def parse_vtt(text: str) -> list[Utterance]:
    """WebVTT — the usual export from a meeting recording."""
    out: list[Utterance] = []
    for match in P.VTT_SPEAKER_RE.finditer(text):
        speaker = match.group(1).strip()
        body = re.sub(r"\s+", " ", match.group(2).strip())
        if body:
            out.append(Utterance(speaker, body))
    if out:
        return out

    # No <v> tags: fall back to cue bodies shaped as "Name: text".
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        for line in lines:
            if "-->" in line or P.TIMESTAMP_RE.match(line):
                continue
            m = re.match(r"^([A-Z][\w'.\-\s]{0,40}?):\s*(.+)$", line)
            if m:
                out.append(Utterance(m.group(1).strip(), m.group(2).strip()))
    return out


def parse_docx(path: Path) -> list[Utterance]:
    """Word transcript from a meeting recording's 'Save transcript' option."""
    try:
        from docx import Document  # type: ignore[import-untyped]
    except ImportError as e:
        raise MissingDependency("python-docx", "docx", "Reading .docx transcripts") from e

    doc = Document(str(path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    out: list[Utterance] = []
    speaker: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if speaker and buf:
            body = " ".join(buf).strip()
            if body:
                out.append(Utterance(speaker, body))
        buf = []

    for line in lines:
        m = P.DOCX_SPEAKER_LINE_RE.match(line)
        if m:
            flush()
            speaker = m.group(1).strip()
            if tail := m.group(3).strip():
                buf.append(tail)
            continue
        only = P.DOCX_SPEAKER_ONLY_RE.match(line)
        if only and len(line) < 80:
            flush()
            speaker = only.group(1).strip()
            continue
        buf.append(line)
    flush()
    return out


def parse_markdown(text: str) -> list[Utterance]:
    """Markdown or plain text, in the shapes transcription tools actually emit.

    Bold speaker prefixes, plain "Name: text", bracketed names, list bullets,
    leading timestamps, and speaker-on-its-own-line followed by dialogue.
    Frontmatter, rules, tables and platform chatter are dropped.

    With no speaker structure at all the whole body comes back as one
    UNATTRIBUTED utterance rather than nothing — the content is still usable,
    and the caller can be honest about attribution instead of inventing it.
    """
    body_text = strip_frontmatter(text)
    out: list[Utterance] = []
    speaker: str | None = None
    buf: list[str] = []
    saw_speaker = False

    def flush() -> None:
        nonlocal buf
        if speaker and buf:
            body = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if body:
                out.append(Utterance(speaker, body))
        buf = []

    for raw in body_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if P.NOISE_RE.match(line) or P.SYSTEM_RE.match(line):
            continue

        stripped = P.LEADING_TS_RE.sub("", line, count=1)

        heading = (
            P.SPEAKER_HEADING_HASH_RE.match(stripped)
            or P.SPEAKER_HEADING_RE.match(stripped)
            or P.SPEAKER_HEADING_TS_RE.match(stripped)
            or P.SPEAKER_BARE_TS_RE.match(stripped)
        )
        if heading and plausible_speaker(heading.group("name")):
            flush()
            speaker = heading.group("name").strip()
            saw_speaker = True
            continue

        if P.ANY_HEADING_RE.match(stripped):
            continue

        prefixed = P.SPEAKER_PREFIX_RE.match(stripped)
        if prefixed and plausible_speaker(prefixed.group("name")):
            flush()
            speaker = prefixed.group("name").strip()
            saw_speaker = True
            # "**Name:**" puts the closing emphasis AFTER the colon, so strip
            # any emphasis left stranded at the front of the text.
            body = re.sub(r"^(?:\*{1,2}|_{1,2})\s*", "", prefixed.group("text").strip()).strip()
            if body:
                buf.append(body)
            continue

        cleaned = re.sub(r"^\s*[-*+]\s+", "", stripped).strip()
        cleaned = re.sub(r"^\s*>\s?", "", cleaned).strip()
        cleaned = re.sub(r"^(?:\*{1,2}|_{1,2})\s*", "", cleaned).strip()
        if cleaned:
            buf.append(cleaned)

    flush()

    if not saw_speaker:
        body = re.sub(r"\s+", " ", body_text).strip()
        return [Utterance(P.UNATTRIBUTED, body)] if body else []
    return out
