"""Linux capture — not implemented yet.

Present so the shape of the work is documented rather than discovered later.

Linux is the easiest of the three: PulseAudio and PipeWire both expose every
output as a `.monitor` source, so system audio is an ordinary input with no
extra permission and no virtual device to install. The likely implementation is
sounddevice (PortAudio) for both tracks, picking the monitor source that
corresponds to the default sink:

    pactl get-default-sink        ->  alsa_output.pci-0000_00_1f.3.analog-stereo
    monitor source                ->  <that>.monitor

Implementing this means filling in `devices()` and `record()` below; nothing
else in saidso needs to change.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..errors import CaptureUnavailable
from .base import CaptureBackend, Device


class PulseBackend(CaptureBackend):
    id = "pulse"
    platform_hint = "Linux (not yet implemented)"

    @classmethod
    def available(cls) -> bool:
        return False

    def devices(self) -> list[Device]:
        raise CaptureUnavailable(
            "Linux live capture isn't implemented yet. Transcribing recording "
            "files works today: saidso transcribe <file>"
        )

    def record(self, device: Device, path: Path, stop: threading.Event) -> None:
        raise CaptureUnavailable("Linux live capture isn't implemented yet.")
