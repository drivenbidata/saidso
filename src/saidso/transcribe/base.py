"""The transcription interface.

One method, one shape of result. Keeping this abstract is what allows a future
backend - whisper.cpp, a hosted API for people who want speed over privacy - to
drop in without touching the recorder or the writers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Segment

# Called with (fraction_complete, message). Fraction is None when unknown.
ProgressFn = Callable[[float | None, str], None]


@dataclass(slots=True)
class TranscriptionResult:
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None
    duration: float | None = None

    def __bool__(self) -> bool:
        return bool(self.segments)


class Transcriber(ABC):
    id: str = "base"

    @abstractmethod
    def transcribe(
        self,
        path: Path,
        *,
        language: str | None = None,
        progress: ProgressFn | None = None,
    ) -> TranscriptionResult:
        """Turn an audio or video file into timed segments."""
