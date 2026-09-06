"""Core data types shared across the pipeline.

Everything downstream of transcription speaks in `Segment`s; everything
downstream of parsing speaks in `Utterance`s. `TranscriptMeta` is what ends up
in the transcript's YAML frontmatter, which is the handle both agents and
humans key on later, so it is treated as part of the output contract.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(slots=True)
class Segment:
    """One timed chunk of speech, as a transcription engine emits it."""

    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass(slots=True)
class Utterance:
    """One turn of dialogue after parsing, with timing discarded."""

    speaker: str
    text: str


@dataclass(slots=True)
class TranscriptMeta:
    """Everything known about a meeting that isn't the dialogue itself."""

    title: str
    when: dt.datetime
    source: str
    project: str = ""
    duration: float | None = None
    language: str | None = None
    link: str = ""
    participants: list[str] = field(default_factory=list)
    date_source: str = "recorded"  # recorded | filename | mtime | given

    @property
    def date(self) -> dt.date:
        return self.when.date()

    # Sources that are a guess rather than a statement. A filename date is
    # authoritative — someone or something asserted it — whereas a modification
    # time is circumstantial: a batch of transcripts downloaded together all
    # share one, and it is the download date, not the meeting date.
    INFERRED_SOURCES = ("mtime",)

    @property
    def date_inferred(self) -> bool:
        """True when the date was guessed rather than stated."""
        return self.date_source in self.INFERRED_SOURCES


def format_timestamp(seconds: float, *, millis: bool = False) -> str:
    """HH:MM:SS, or HH:MM:SS.mmm for VTT cues."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if millis:
        return f"{h:02d}:{m:02d}:{seconds % 60:06.3f}"
    return f"{h:02d}:{m:02d}:{int(seconds % 60):02d}"
