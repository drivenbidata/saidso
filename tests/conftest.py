from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saidso.config import Config, Project  # noqa: E402


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        notes_dir=tmp_path / "notes",
        speaker_name="Javi Gold",
        default_project="general",
        projects=(
            Project("acme", "Acme Corp", "acme"),
            Project("Orbit8", "Orbit8", "Orbit8"),
            Project("general", "General", "general"),
            Project("retired", "Retired", "retired", active=False),
        ),
    )
