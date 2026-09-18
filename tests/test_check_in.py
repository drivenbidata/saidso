"""The long-recording check-in, and participants entered while recording.

Both exist because of the same failure: a recording nobody stopped. The
watchdog is tested against a real `Recorder` driven by a fake backend, because
the bug it prevents is a threading bug and testing the timer in isolation would
not have caught it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from saidso.capture.base import LOOPBACK, MIC, CaptureBackend, Device
from saidso.config import Config
from saidso.pipeline import LiveSession

# Short enough that the suite stays fast, long enough to survive a loaded CI box.
TICK = 0.05


class FakeBackend(CaptureBackend):
    """Records silence into a real file until told to stop."""

    id = "fake"

    @classmethod
    def available(cls) -> bool:
        return True

    def devices(self) -> list[Device]:
        return [
            Device(0, "Fake Mic", MIC, is_default=True),
            Device(1, "Fake Speakers", LOOPBACK, is_default=True),
        ]

    def record(self, device: Device, path: Path, stop: threading.Event) -> None:
        path.write_bytes(b"\0" * 2048)
        stop.wait()


@pytest.fixture
def live(cfg: Config, tmp_path, monkeypatch):
    """Build a LiveSession on fake hardware, with a factory for the timings."""
    monkeypatch.setattr("saidso.pipeline.get_backend", lambda _backend: FakeBackend())
    monkeypatch.setattr("saidso.paths.recordings_dir", lambda: tmp_path / "rec")

    sessions: list[LiveSession] = []

    def build(*, after=TICK, grace=TICK, **kwargs) -> LiveSession:
        tuned = replace(
            cfg, capture=replace(cfg.capture, check_in_after=after, check_in_grace=grace)
        )
        # The settings are whole seconds on disk; the floats the session works
        # in are what the watchdog actually waits on, so they are set directly.
        session = LiveSession(tuned, title="Long One", **kwargs)
        session.check_in_after = after
        session.check_in_grace = grace
        sessions.append(session)
        return session

    yield build
    for session in sessions:
        if session.running:
            session.cancel()


def _wait(predicate, timeout=5.0):
    """Wait for a condition rather than sleeping a guessed interval."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- watchdog


def test_asks_once_the_interval_has_passed(live):
    asked = threading.Event()
    session = live(on_check_in=lambda elapsed, grace: asked.set())
    session.start()

    assert asked.wait(5), "the check-in never fired"
    assert session.awaiting_check_in
    session.cancel()


def test_stops_when_nothing_answers(live):
    expired = threading.Event()
    session = live(on_check_in=lambda *_: None, on_expire=expired.set)
    session.start()

    assert expired.wait(5), "the recording was never stopped"


def test_confirming_keeps_recording_and_asks_again(live):
    asks = []
    expired = threading.Event()

    def on_check_in(elapsed, grace):
        asks.append(elapsed)

    session = live(on_check_in=on_check_in, on_expire=expired.set)
    session.start()

    # Answer each check-in as it arrives. A 6-hour recording is exactly what
    # happens when the watchdog asks once and then gives up asking.
    for round_number in range(1, 4):
        assert _wait(lambda n=round_number: len(asks) >= n), "the check-in did not re-arm"
        session.confirm()

    assert len(asks) >= 3
    assert not expired.is_set(), "confirmed sessions must not be auto-stopped"
    assert session.running
    session.cancel()


def test_warn_only_never_stops(live):
    """The CLI passes no on_expire: it should nag forever, not auto-stop."""
    asks = []
    session = live(on_check_in=lambda elapsed, grace: asks.append(elapsed))
    session.start()

    assert _wait(lambda: len(asks) >= 3, timeout=5), "warn-only stopped asking"
    assert session.running
    session.cancel()


def test_zero_interval_disables_the_watchdog(live):
    asked = threading.Event()
    session = live(after=0, on_check_in=lambda *_: None if asked.set() else None)
    session.start()

    time.sleep(TICK * 6)
    assert not asked.is_set()
    assert session._watchdog is None
    session.cancel()


def test_a_failing_listener_does_not_stop_the_recording(live):
    """A closed window must not take the meeting with it."""
    def boom(*_args):
        raise RuntimeError("window is gone")

    expired = threading.Event()
    session = live(on_check_in=boom, on_expire=expired.set)
    session.start()

    # The callback blew up, so nobody can answer — which is precisely when the
    # auto-stop has to still work.
    assert expired.wait(5), "an unreachable UI should still end in an auto-stop"


def test_cancel_releases_the_watchdog(live):
    session = live(after=10, on_check_in=lambda *_: None)
    session.start()
    session.cancel()
    assert _wait(lambda: not session._watchdog.is_alive()), "watchdog outlived the session"


def test_remaining_counts_down_and_clears(live):
    session = live(after=TICK, grace=5.0, on_check_in=lambda *_: None)
    session.start()

    assert _wait(lambda: session.awaiting_check_in)
    remaining = session.check_in_remaining()
    assert remaining is not None and 0 < remaining <= 5.0

    session.confirm()
    assert session.check_in_remaining() is None
    assert not session.awaiting_check_in
    session.cancel()


# ------------------------------------------------------------ participants


def test_participants_are_additive_and_deduplicated(live):
    session = live(after=0, participants=["Alex Rivera"])

    assert session.add_participants(["sam@example.com"]) == ["Alex Rivera", "sam@example.com"]
    # Same person, different capitalisation and whitespace: still one person.
    assert session.add_participants(["  alex rivera  ", ""]) == [
        "Alex Rivera",
        "sam@example.com",
    ]


def test_participants_reach_the_transcript(live, monkeypatch):
    """Names added mid-recording are what the frontmatter is written from."""
    from saidso.models import Segment
    from saidso.pipeline import MergedTracks

    session = live(after=0, participants=["Alex Rivera"])
    session.start()
    session.add_participants(["Sam"])

    monkeypatch.setattr(
        "saidso.pipeline.merge_tracks",
        lambda *a, **k: MergedTracks(segments=[Segment(0.0, 1.0, "Hi", "Alex Rivera")]),
    )
    outcome = session.stop()

    assert outcome.meta.participants == ["Alex Rivera", "Sam"]
    written = outcome.transcript.read_text(encoding="utf-8")
    assert "participants:" in written
    assert "- Alex Rivera" in written
    assert "- Sam" in written
