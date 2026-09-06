"""Optional speaker diarisation with pyannote.audio.

Strictly an add-on. saidso's two-track recording already separates you from
everyone else without a model; diarisation only exists to split that "everyone
else" track into Speaker 1 / Speaker 2 / ..., and to label speakers in a
recording file that arrived as a single mixed track.

It stays optional because the cost is real: a large extra dependency, a Hugging
Face account, and accepting the model terms. Everything works without it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..models import Segment

TOKEN_ENV_VARS = ("SAIDSO_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN")
MODEL_ID = "pyannote/speaker-diarization-3.1"


@dataclass(frozen=True, slots=True)
class DiarizationResult:
    applied: bool
    speakers: int = 0
    reason: str = ""


def find_token() -> str | None:
    for var in TOKEN_ENV_VARS:
        if value := os.environ.get(var, "").strip():
            return value
    return None


def apply(
    audio: Path,
    segments: list[Segment],
    *,
    token: str | None = None,
    label: str = "Speaker",
) -> DiarizationResult:
    """Label `segments` in place by speaker. Never raises — reports instead.

    A meeting with unlabelled speakers is still a useful meeting, so every
    failure path here degrades to "not applied, and here's why" rather than
    losing the transcript.
    """
    token = token or find_token()
    if not token:
        return DiarizationResult(
            False,
            reason=(
                "no Hugging Face token — set SAIDSO_HF_TOKEN, then accept the terms "
                f"at huggingface.co/{MODEL_ID}"
            ),
        )
    try:
        from pyannote.audio import Pipeline  # type: ignore[import-untyped]
    except ImportError:
        return DiarizationResult(
            False, reason="pyannote.audio isn't installed — pip install 'saidso[diarize]'"
        )

    try:
        pipeline = Pipeline.from_pretrained(MODEL_ID, use_auth_token=token)
        diarization = pipeline(str(audio))
    except Exception as e:  # noqa: BLE001 - third-party failures are many and uninteresting
        return DiarizationResult(False, reason=f"diarisation failed: {e}")

    turns = [(t.start, t.end, spk) for t, _, spk in diarization.itertracks(yield_label=True)]
    if not turns:
        return DiarizationResult(False, reason="no speaker turns detected")

    # Assign each transcript segment the speaker whose turn overlaps it most.
    # Whisper's segment boundaries and pyannote's turn boundaries never align,
    # so "most overlap" is the only stable rule available.
    names: dict[str, str] = {}
    for seg in segments:
        best, best_overlap = None, 0.0
        for start, end, spk in turns:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > best_overlap:
                best, best_overlap = spk, overlap
        if best is not None:
            if best not in names:
                names[best] = f"{label} {len(names) + 1}"
            seg.speaker = names[best]

    return DiarizationResult(True, speakers=len(names))
