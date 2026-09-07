"""SAIDSO_HOME is the sandbox switch: tests, dev runs and the desktop shell's
dev mode all rely on it. An override that isolates only some paths is worse
than none, because it reads as complete.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from saidso import config as config_mod
from saidso import paths


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("SAIDSO_HOME", str(tmp_path))
    return tmp_path


def test_saidso_home_isolates_every_location(sandbox):
    for location in (paths.config_dir(), paths.data_dir(), paths.cache_dir(),
                     paths.config_file(), paths.recordings_dir(), paths.default_notes_dir()):
        assert sandbox in location.parents or location == sandbox, location


def test_a_sandboxed_starter_config_does_not_point_at_the_real_home(sandbox):
    """The leak this pins: config in the sandbox, notes in the user's home."""
    cfg = config_mod.load(create=True)
    assert sandbox in cfg.notes_dir.parents
    assert cfg.notes_dir != Path.home() / "saidso"
    assert sandbox in cfg.inbox_dir.parents


def test_without_the_override_the_default_is_the_users_home(monkeypatch):
    monkeypatch.delenv("SAIDSO_HOME", raising=False)
    assert paths.default_notes_dir() == Path.home() / "saidso"


def test_an_explicit_notes_dir_still_wins(sandbox, tmp_path):
    elsewhere = tmp_path / "chosen"
    cfg = config_mod.starter(notes_dir=elsewhere)
    assert cfg.notes_dir == elsewhere
