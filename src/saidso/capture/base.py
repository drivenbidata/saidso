"""The capture interface every platform backend implements.

Live capture is the least portable part of saidso: Windows has WASAPI loopback,
macOS needs ScreenCaptureKit or a virtual device, Linux has PipeWire monitors.
Keeping that behind one small interface means adding a platform is writing one
file, not unpicking the recorder.

A backend records to WAV and nothing else. Transcription, mixing and labelling
all happen downstream, so a backend can be tested by listening to the files.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

MIC = "mic"
LOOPBACK = "loopback"


@dataclass(frozen=True, slots=True)
class Device:
    """An input saidso can record from."""

    index: int
    name: str
    kind: str  # MIC | LOOPBACK
    channels: int = 1
    sample_rate: int = 48000
    is_default: bool = False

    def __str__(self) -> str:
        mark = " (default)" if self.is_default else ""
        return f"[{self.index}] {self.name}{mark}"


class CaptureBackend(ABC):
    """Enumerates inputs and writes raw audio to WAV files."""

    id: str = "base"
    platform_hint: str = ""

    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """True when this backend can run here — right OS, dependency installed."""

    @abstractmethod
    def devices(self) -> list[Device]:
        """Every recordable input, microphones and loopbacks together."""

    def microphones(self) -> list[Device]:
        return [d for d in self.devices() if d.kind == MIC]

    def loopbacks(self) -> list[Device]:
        return [d for d in self.devices() if d.kind == LOOPBACK]

    def resolve(self, query: str | None, kind: str) -> Device | None:
        """Find a device by index or name fragment; fall back to the default.

        Name matching is a case-insensitive substring so a config written on one
        machine survives a driver renaming "Speakers (Realtek Audio)" slightly.
        """
        pool = [d for d in self.devices() if d.kind == kind]
        if not pool:
            return None
        q = (query or "").strip()
        if not q:
            return next((d for d in pool if d.is_default), pool[0])
        if q.isdigit():
            idx = int(q)
            return next((d for d in pool if d.index == idx), None)
        low = q.lower()
        return next((d for d in pool if low in d.name.lower()), None)

    @abstractmethod
    def record(self, device: Device, path: Path, stop: threading.Event) -> None:
        """Record `device` into `path` until `stop` is set. Blocking."""

    def close(self) -> None:  # noqa: B027 - an optional hook, not a requirement
        """Release any platform handles. Safe to call more than once.

        Deliberately concrete and empty: a backend that holds nothing has
        nothing to release, and shouldn't be forced to say so.
        """
