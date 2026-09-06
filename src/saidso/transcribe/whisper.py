"""Local transcription with faster-whisper.

Runs on the machine, so audio never leaves it — the property the tool this grew
out of was built for, and the reason the default stays local even though a
hosted API would be quicker.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import MissingDependency, SaidsoError
from ..models import Segment
from .base import ProgressFn, Transcriber, TranscriptionResult

MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3")
DEFAULT_MODEL = "base"

# Loading a model costs seconds and hundreds of MB, and a batch run transcribes
# many files with the same one, so instances are shared process-wide.
_cache: dict[tuple[str, str, str], object] = {}


def clear_model_cache() -> None:
    _cache.clear()


def load_model(name: str = DEFAULT_MODEL, *, device: str = "auto", compute_type: str = "auto"):
    """Load (and cache) a faster-whisper model, falling back to CPU int8.

    The fallback matters on machines with a GPU that CTranslate2 can see but
    can't use — a missing cuDNN, a driver mismatch. Failing over to CPU is
    slower but keeps the meeting; raising would lose it.
    """
    key = (name, device, compute_type)
    if key in _cache:
        return _cache[key]
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError as e:
        raise MissingDependency("faster-whisper", "transcribe", "Transcription") from e

    try:
        model = WhisperModel(name, device=device, compute_type=compute_type)
    except Exception:
        try:
            model = WhisperModel(name, device="cpu", compute_type="int8")
        except Exception as e:
            raise SaidsoError(
                f"Could not load the Whisper model {name!r}: {e}\n"
                "The first run downloads it, so check the network, then try a "
                "smaller model with --model tiny."
            ) from e
    _cache[key] = model
    return model


class WhisperTranscriber(Transcriber):
    id = "faster-whisper"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        device: str = "auto",
        compute_type: str = "auto",
        vad_filter: bool = True,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter

    def transcribe(
        self,
        path: Path,
        *,
        language: str | None = None,
        progress: ProgressFn | None = None,
    ) -> TranscriptionResult:
        path = Path(path)
        if not path.exists():
            raise SaidsoError(f"No such audio file: {path}")

        if progress:
            progress(None, f"Loading model {self.model_name}")
        model = load_model(self.model_name, device=self.device, compute_type=self.compute_type)

        if progress:
            progress(0.0, f"Transcribing {path.name}")
        segments_iter, info = model.transcribe(
            str(path),
            language=language or None,
            vad_filter=self.vad_filter,
        )

        total = float(getattr(info, "duration", 0.0) or 0.0)
        segments: list[Segment] = []
        # faster-whisper yields lazily, so this loop is where the time goes and
        # the only place a progress fraction can come from.
        for s in segments_iter:
            segments.append(Segment(start=s.start, end=s.end, text=s.text))
            if progress and total > 0:
                progress(min(s.end / total, 1.0), f"Transcribing {path.name}")

        if progress:
            progress(1.0, f"Transcribed {path.name}")
        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None),
            duration=total or (segments[-1].end if segments else None),
        )
