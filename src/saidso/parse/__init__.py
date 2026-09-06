"""Transcript parsing: any supported format in, clean dialogue out.

    from saidso.parse import parse_file
    result = parse_file(Path("meeting.vtt"))
    result.utterances  # [Utterance(speaker, text), ...]
    result.speakers    # ["Ana Ruiz", "Ben Okafor"]  - order of first appearance

Supported: .vtt, .docx, .md/.markdown, .txt/.text. Unknown extensions are read
as text rather than refused, since pasted dialogue arrives with every extension
imaginable and the markdown reader copes with all of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ParseError
from ..models import Utterance
from . import patterns as P
from .formats import parse_docx, parse_markdown, parse_vtt

__all__ = ["ParseResult", "parse_file", "parse_text", "merge_contiguous", "normalize_speaker"]

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ""}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".vtt", ".docx"}


@dataclass(slots=True)
class ParseResult:
    utterances: list[Utterance] = field(default_factory=list)
    source: Path | None = None

    @property
    def speakers(self) -> list[str]:
        """Unique speakers in order of first appearance."""
        seen: list[str] = []
        for u in self.utterances:
            if u.speaker not in seen:
                seen.append(u.speaker)
        return seen

    @property
    def attributed(self) -> bool:
        """False when the source had no speaker structure to work with."""
        return self.speakers not in ([], [P.UNATTRIBUTED])

    def as_log(self) -> str:
        """The clean 'Speaker: text' log an agent reads."""
        return "\n".join(f"{u.speaker}: {u.text}" for u in self.utterances)


def normalize_speaker(name: str) -> str:
    """Collapse whitespace and strip a trailing colon from a speaker name."""
    return re.sub(r"\s+", " ", name).strip().rstrip(":")


def merge_contiguous(utterances: list[Utterance]) -> list[Utterance]:
    """Merge back-to-back turns from the same speaker into one utterance."""
    merged: list[Utterance] = []
    for u in utterances:
        speaker = normalize_speaker(u.speaker)
        if merged and merged[-1].speaker == speaker:
            merged[-1].text = f"{merged[-1].text} {u.text}"
        else:
            merged.append(Utterance(speaker, u.text))
    return merged


def parse_text(text: str, *, fmt: str = "md") -> ParseResult:
    """Parse an in-memory transcript. `fmt` is 'vtt' or anything else for text."""
    raw = parse_vtt(text) if fmt == "vtt" else parse_markdown(text)
    return ParseResult(merge_contiguous(raw))


def parse_file(path: Path) -> ParseResult:
    """Parse a transcript file, dispatching on its extension."""
    path = Path(path)
    if not path.exists():
        raise ParseError(f"No such transcript: {path}")

    suffix = path.suffix.lower()
    if suffix == ".vtt":
        raw = parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
    elif suffix == ".docx":
        raw = parse_docx(path)
    else:
        raw = parse_markdown(path.read_text(encoding="utf-8", errors="replace"))

    result = ParseResult(merge_contiguous(raw), source=path)
    if not result.utterances:
        raise ParseError(
            f"Nothing parsed from {path.name} — the file may be empty, or in a layout "
            "saidso doesn't recognise yet."
        )
    return result
