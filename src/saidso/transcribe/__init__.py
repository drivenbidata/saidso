"""Audio in, timed segments out.

    from saidso.transcribe import WhisperTranscriber
    result = WhisperTranscriber("base").transcribe(Path("meeting.mp4"))
"""

from __future__ import annotations

from .base import ProgressFn, Transcriber, TranscriptionResult
from .diarize import DiarizationResult
from .diarize import apply as diarize
from .whisper import DEFAULT_MODEL, MODELS, WhisperTranscriber, clear_model_cache, load_model

__all__ = [
    "DEFAULT_MODEL",
    "MODELS",
    "DiarizationResult",
    "ProgressFn",
    "Transcriber",
    "TranscriptionResult",
    "WhisperTranscriber",
    "clear_model_cache",
    "diarize",
    "load_model",
]

MEDIA_SUFFIXES = frozenset(
    {
        ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg", ".oga", ".flac",
        ".mkv", ".mov", ".aac", ".wma", ".avi", ".opus", ".m4v", ".wmv",
    }
)


def is_media(path) -> bool:
    from pathlib import Path

    return Path(path).suffix.lower() in MEDIA_SUFFIXES
