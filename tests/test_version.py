"""The version appears in the Python package and in the desktop app's
package.json. They must agree.

Not pedantry: Squirrel decides whether an installer is an upgrade by comparing
versions. A desktop build that still claims the installed version will not
replace anything, and the installer appears to do nothing at all.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import saidso

ROOT = Path(__file__).resolve().parents[1]


def test_the_desktop_app_and_the_engine_report_the_same_version():
    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == saidso.__version__


def test_the_version_is_declared_once():
    """pyproject reads it from the package instead of repeating it."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"], "a second copy of the version drifts"
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/saidso/__init__.py"


def test_the_version_looks_like_a_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.-]\w+)?", saidso.__version__)
