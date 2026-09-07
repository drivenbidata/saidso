"""Where saidso keeps its own files.

Config, state and cached models live in per-user OS locations, never inside the
notes directory and never inside the source tree. The prototype this grew out of
kept its config in the repo it was writing to, which made the tool inseparable
from one person's vault; keeping them apart is most of what "productised" means
here.

Every location can be overridden with SAIDSO_HOME, which is what the test suite
and the Electron shell's dev mode use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "saidso"


def _env_home() -> Path | None:
    raw = os.environ.get("SAIDSO_HOME", "").strip()
    return Path(raw).expanduser() if raw else None


def config_dir() -> Path:
    """Directory holding config.toml."""
    if (home := _env_home()) is not None:
        return home
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def data_dir() -> Path:
    """Directory for state saidso maintains but the user doesn't edit."""
    if (home := _env_home()) is not None:
        return home / "data"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def cache_dir() -> Path:
    """Directory for things that can be deleted and re-downloaded (models, temp audio)."""
    if (home := _env_home()) is not None:
        return home / "cache"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def recordings_dir() -> Path:
    """Scratch space for live audio, before and during transcription.

    Deliberately outside the notes directory: half-written WAVs must never land
    somewhere a sync job might pick them up.
    """
    return cache_dir() / "recordings"


def default_notes_dir() -> Path:
    """The notes library used when the user hasn't chosen one.

    Respects SAIDSO_HOME, so that variable really does isolate everything. It
    did not, once: config went to the sandbox while notes still went to the
    real `~/saidso`, and a test run that looked self-contained quietly wrote a
    transcript into a person's actual notes folder. An override that isolates
    only some paths is worse than none, because it reads as complete.
    """
    if (home := _env_home()) is not None:
        return home / "notes"
    return Path.home() / "saidso"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
