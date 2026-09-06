"""Live audio capture: backend selection and two-track recording.

    backend = get_backend()                  # whatever works on this machine
    rec = Recorder(backend, mic=..., system=...)
    rec.start(); ...; tracks = rec.stop()

Two tracks, not a mix. The microphone track is you and the loopback track is
everyone else, which means saidso can label your own speech correctly with no
model involved — diarisation is then only needed to split the *other* track
into individuals, and stays optional.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..errors import CaptureUnavailable
from .base import LOOPBACK, MIC, CaptureBackend, Device

__all__ = [
    "CaptureBackend",
    "Device",
    "MIC",
    "LOOPBACK",
    "Recorder",
    "Track",
    "get_backend",
    "available_backends",
]


def _registry() -> list[type[CaptureBackend]]:
    from .coreaudio import CoreAudioBackend
    from .pulse import PulseBackend
    from .wasapi import WasapiBackend

    return [WasapiBackend, CoreAudioBackend, PulseBackend]


def available_backends() -> list[type[CaptureBackend]]:
    return [b for b in _registry() if b.available()]


def get_backend(name: str = "auto") -> CaptureBackend:
    """Return a usable capture backend, or explain precisely why there isn't one."""
    name = (name or "auto").strip().lower()

    if name == "none":
        raise CaptureUnavailable("Capture is disabled (capture.backend = \"none\").")

    if name != "auto":
        for backend in _registry():
            if backend.id == name:
                if not backend.available():
                    raise CaptureUnavailable(
                        f"Capture backend {name!r} isn't usable here. It needs "
                        f"{backend.platform_hint or 'a supported platform'}."
                    )
                return backend()
        known = ", ".join(b.id for b in _registry())
        raise CaptureUnavailable(f"Unknown capture backend {name!r}. Known: {known}.")

    for backend in _registry():
        if backend.available():
            return backend()

    import sys

    raise CaptureUnavailable(
        f"No capture backend is available on {sys.platform}.\n"
        "On Windows, install the extra:  pip install 'saidso[capture]'\n"
        "Recording files can still be transcribed with:  saidso transcribe <file>"
    )


@dataclass(frozen=True, slots=True)
class Track:
    """One recorded audio file and what it represents."""

    label: str  # "mic" or "system"
    path: Path
    device: Device


class Recorder:
    """Records microphone and system audio to separate WAV files."""

    def __init__(
        self,
        backend: CaptureBackend,
        *,
        mic: Device | None,
        system: Device | None,
        dest_dir: Path,
        basename: str,
    ) -> None:
        if mic is None and system is None:
            raise CaptureUnavailable(
                "Nothing to record: neither a microphone nor a system-audio device "
                "was found. Run `saidso devices` to see what this machine offers."
            )
        self.backend = backend
        self.mic = mic
        self.system = system
        self.dest_dir = Path(dest_dir)
        self.basename = basename
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._errors: list[BaseException] = []
        self._tracks: list[Track] = []
        self._started_at: float | None = None

    @property
    def running(self) -> bool:
        return self._started_at is not None and not self._stop.is_set()

    @property
    def elapsed(self) -> float:
        return 0.0 if self._started_at is None else time.time() - self._started_at

    def start(self) -> None:
        if self._started_at is not None:
            raise CaptureUnavailable("This recorder has already been started.")
        self.dest_dir.mkdir(parents=True, exist_ok=True)

        planned = [(MIC, self.mic), (LOOPBACK, self.system)]
        for label, device in planned:
            if device is None:
                continue
            name = "mic" if label == MIC else "system"
            path = self.dest_dir / f"{self.basename}_{name}.wav"
            self._tracks.append(Track(name, path, device))

            def run(d: Device = device, p: Path = path) -> None:
                try:
                    self.backend.record(d, p, self._stop)
                except BaseException as exc:  # noqa: BLE001 - reported to the caller
                    self._errors.append(exc)
                    self._stop.set()  # one dead track shouldn't leave the other running

            thread = threading.Thread(target=run, daemon=True, name=f"saidso-capture-{name}")
            self._threads.append(thread)
            thread.start()

        self._started_at = time.time()

    def stop(self, timeout: float = 5.0) -> list[Track]:
        """Stop recording and return the tracks that hold audio.

        Tracks too small to contain speech are dropped rather than handed on:
        an empty WAV costs a pointless model load downstream, and a muted mic is
        the normal case, not an error.
        """
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        if self._errors:
            raise CaptureUnavailable(f"Recording failed: {self._errors[0]}") from self._errors[0]
        return [t for t in self._tracks if t.path.exists() and t.path.stat().st_size > 1024]
