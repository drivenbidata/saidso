"""Windows capture via WASAPI loopback (PyAudioWPatch).

Loopback is what makes an unattended meeting recorder possible on Windows: the
same audio the speakers are playing can be opened as an input, so the other
participants are captured without a virtual cable or a platform-specific bot.
The microphone is recorded as a second, separate track — keeping them apart is
what lets saidso label your own speech reliably without any diarisation model.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

from ..errors import CaptureUnavailable, MissingDependency
from .base import LOOPBACK, MIC, CaptureBackend, Device

FRAMES_PER_BUFFER = 2048
# How long to wait when the device has nothing ready. Short enough that stopping
# feels instant, long enough that an idle loopback costs nothing.
POLL_INTERVAL = 0.01

# PortAudio's initialise, terminate and device enumeration are process-global and
# not thread-safe. Two threads calling Pa_Initialize() at the same moment is not
# a race that produces a wrong answer — it is an access violation that kills the
# process outright, taking any recording in progress with it.
#
# This is easy to hit without meaning to: two windows asking which microphones
# exist, or one window asking twice, is enough. The lock is module-level rather
# than per-instance because the thing being protected belongs to the library,
# not to any one backend object.
_PORTAUDIO_LOCK = threading.RLock()


def _pyaudio():
    try:
        import pyaudiowpatch as pyaudio  # type: ignore[import-untyped]
    except ImportError as e:
        raise MissingDependency("PyAudioWPatch", "capture", "Live recording on Windows") from e
    return pyaudio


class WasapiBackend(CaptureBackend):
    id = "wasapi"
    platform_hint = "Windows"

    def __init__(self) -> None:
        self._pa = None
        self._pyaudio = None

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def available(cls) -> bool:
        import sys

        if sys.platform != "win32":
            return False
        try:
            import pyaudiowpatch  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            return False
        return True

    def _handle(self):
        with _PORTAUDIO_LOCK:
            if self._pa is None:
                self._pyaudio = _pyaudio()
                self._pa = self._pyaudio.PyAudio()
            return self._pa

    def close(self) -> None:
        with _PORTAUDIO_LOCK:
            if self._pa is not None:
                self._pa.terminate()
                self._pa = None

    # ------------------------------------------------------------ enumeration

    def _default_output_name(self) -> str:
        pa, pyaudio = self._handle(), self._pyaudio
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as e:
            raise CaptureUnavailable(
                "WASAPI is not available on this machine, so system audio can't be "
                "captured. You can still transcribe recording files."
            ) from e
        return str(pa.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"])

    def devices(self) -> list[Device]:
        # The whole enumeration is inside the lock, not just the handle: walking
        # the device list is itself a PortAudio call, and a device appearing or
        # disappearing mid-walk is the other way this crashes.
        with _PORTAUDIO_LOCK:
            return self._devices_locked()

    def _devices_locked(self) -> list[Device]:
        pa = self._handle()
        out: list[Device] = []

        try:
            default_mic_index = int(pa.get_default_input_device_info()["index"])
        except OSError:
            default_mic_index = -1

        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("maxInputChannels", 0) > 0 and not d.get("isLoopbackDevice"):
                out.append(
                    Device(
                        index=int(d["index"]),
                        name=str(d["name"]),
                        kind=MIC,
                        channels=int(d["maxInputChannels"]),
                        sample_rate=int(d["defaultSampleRate"]),
                        is_default=int(d["index"]) == default_mic_index,
                    )
                )

        try:
            default_out = self._default_output_name()
        except CaptureUnavailable:
            default_out = ""

        for d in pa.get_loopback_device_info_generator():
            name = str(d["name"])
            out.append(
                Device(
                    index=int(d["index"]),
                    name=name,
                    kind=LOOPBACK,
                    channels=int(d["maxInputChannels"]),
                    sample_rate=int(d["defaultSampleRate"]),
                    # The loopback device's name contains the output device's name,
                    # e.g. "Speakers (Realtek Audio) [Loopback]".
                    is_default=bool(default_out) and default_out in name,
                )
            )
        return out

    # ------------------------------------------------------------ recording

    def record(self, device: Device, path: Path, stop: threading.Event) -> None:
        """Record one device to a WAV file until `stop` is set.

        Blocking, so callers run it on a thread. Cleanup is in `finally` because
        a half-closed WAV has no valid RIFF header and is unreadable — losing a
        whole meeting to an exception on the last buffer is not acceptable.

        The loop polls `get_read_available()` rather than calling `read()`
        straight away, because a WASAPI **loopback** stream delivers nothing at
        all while the machine is playing nothing — not silence, no buffers. A
        blocking `read()` on an idle output therefore never returns, and the
        stop flag is never seen: recording a meeting where nobody unmutes, or
        with the speakers idle, would hang the thread and hold the file open.
        Polling costs a few wake-ups a second and cannot hang.
        """
        pa, pyaudio = self._handle(), self._pyaudio
        rate = int(device.sample_rate)
        channels = min(int(device.channels), 2) or 1

        path.parent.mkdir(parents=True, exist_ok=True)
        stream = None
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(rate)
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=device.index,
                    frames_per_buffer=FRAMES_PER_BUFFER,
                )
                while not stop.is_set():
                    if not self._drain(stream, wf):
                        time.sleep(POLL_INTERVAL)
                # Whatever the device buffered between the last poll and the
                # stop; without this the final fraction of a second is lost.
                self._drain(stream, wf)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()

    @staticmethod
    def _drain(stream, wf) -> bool:
        """Move whatever the device has ready into the file. True if it wrote."""
        try:
            available = stream.get_read_available()
        except OSError:
            return False
        wrote = False
        while available >= FRAMES_PER_BUFFER:
            wf.writeframes(stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False))
            available -= FRAMES_PER_BUFFER
            wrote = True
        return wrote
