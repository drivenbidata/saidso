"""Entry point for the frozen engine.

PyInstaller needs a module-level script to freeze, and the desktop app needs an
executable it can spawn without a Python on the machine. This is that seam —
plus the small amount of diagnostics that a frozen build cannot do without.

A frozen app is a black box when it misbehaves: there is no interpreter to
attach to and no traceback for a hang, only a process sitting there. So
faulthandler is always enabled (it costs nothing until something crashes), and
SAIDSO_STACK_AFTER dumps every thread's stack after N seconds — which is the
only practical way to see where a frozen build is stuck.
"""

from __future__ import annotations

import faulthandler
import multiprocessing
import os
import sys

from saidso.server import main


def _enable_diagnostics() -> None:
    # Turns a silent hard crash in a native extension into a stack trace.
    try:
        faulthandler.enable()
    except (AttributeError, ValueError, OSError):
        return  # no usable stderr, e.g. a windowed build

    after = os.environ.get("SAIDSO_STACK_AFTER", "").strip()
    if not after:
        return
    try:
        seconds = float(after)
    except ValueError:
        return
    if seconds > 0:
        # Every thread, repeatedly, without killing the process: a hang is
        # usually clearer from two dumps than from one.
        faulthandler.dump_traceback_later(seconds, repeat=True, exit=False)


def _preload_runtime() -> None:
    """Import the model runtime on the main thread, before the server starts.

    saidso imports faster-whisper lazily so the CLI stays fast and an optional
    dependency can be missing without breaking startup. In a frozen build that
    backfires: the first import then happens on a worker thread when a
    transcription is requested, and loading numpy's native extension from a
    non-main thread deadlocks against the Windows loader lock. The symptom is a
    transcription that never starts, never fails, and produces no traceback.

    Warming the import here costs a second at launch and removes the class.
    Failing is not fatal — a build without the extra can still serve everything
    that does not transcribe, and the missing-dependency error is far clearer
    when it surfaces from an actual request.
    """
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(f"saidso-engine: model runtime unavailable: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    # ctranslate2 and its dependencies can spawn workers; without this a frozen
    # build re-executes the whole app in each child instead of running the
    # worker, which on Windows means an unbounded fork bomb rather than an error.
    multiprocessing.freeze_support()
    _enable_diagnostics()
    _preload_runtime()
    sys.exit(main())
