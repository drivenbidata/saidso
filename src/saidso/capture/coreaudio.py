"""macOS capture — not implemented yet.

Present so the shape of the work is documented rather than discovered later.

macOS has no equivalent of WASAPI loopback: an app cannot open the system
output as an input without help. Two viable routes, in order of preference:

1. ScreenCaptureKit (macOS 13+) with SCStreamConfiguration.capturesAudio. This
   is the supported, no-install path, but it needs a native extension or a
   PyObjC bridge and triggers a screen-recording permission prompt.
2. A virtual audio device the user installs (BlackHole, Loopback). Trivial to
   implement here - it appears as an ordinary input - but the user must install
   and route it themselves, which is a poor first-run experience.

The microphone half needs neither: sounddevice or PyAudio covers it today.
Implementing this means filling in `devices()` and `record()` below; nothing
else in saidso needs to change.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..errors import CaptureUnavailable
from .base import CaptureBackend, Device


class CoreAudioBackend(CaptureBackend):
    id = "coreaudio"
    platform_hint = "macOS (not yet implemented)"

    @classmethod
    def available(cls) -> bool:
        return False

    def devices(self) -> list[Device]:
        raise CaptureUnavailable(
            "macOS live capture isn't implemented yet. Transcribing recording "
            "files works today: saidso transcribe <file>"
        )

    def record(self, device: Device, path: Path, stop: threading.Event) -> None:
        raise CaptureUnavailable("macOS live capture isn't implemented yet.")
