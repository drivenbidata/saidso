"""stdout has to carry a transcript, not the console's codepage.

`saidso parse` died partway through a real 6h41m transcript with
UnicodeEncodeError, because Windows hands a terminal-launched process a cp1252
stdout and the transcript contained characters outside it. The command exited
non-zero having already written most of a file, which is the worst shape a
failure can take: a truncated output that looks finished.

The regression is forced here by setting PYTHONIOENCODING, so it reproduces on
any platform rather than only on a Windows console.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")

# Curly quotes and an em dash are cp1252-safe; the rest are not, and all of them
# turn up in real transcripts — names, and whatever the transcriber heard.
BEYOND_CP1252 = "Ωmega Zoë — 日本語 — café — 🎤 — Malmö"

TRANSCRIPT = f"""---
title: Encoding Test
date: 2026-09-18
project: general
---

# Encoding Test — Raw Transcript

[00:00:00] **Jeffrey Ford:** {BEYOND_CP1252}
[00:00:05] **Others:** Ordinary ASCII, so a truncated write is visible.
"""


# The console encoding is decided before the process starts, so this has to be
# a real subprocess — capsys would test nothing.
ENTRY = "import sys; from saidso.cli import main; sys.exit(main())"


def _run(target: Path, encoding: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", ENTRY, "parse", str(target)],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": encoding},
        timeout=60,
    )


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    target = tmp_path / "encoding.md"
    target.write_text(TRANSCRIPT, encoding="utf-8")
    return target


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
def test_parse_survives_a_narrow_console(transcript, encoding):
    result = _run(transcript, encoding)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in result.stderr
    # The line after the hard one has to be there: the original bug wrote most
    # of the output and then died, so "it produced something" is not the test.
    assert b"Ordinary ASCII" in result.stdout


def test_the_characters_survive_rather_than_the_command_only_surviving(transcript):
    """A crash traded for silent mojibake would not be a fix."""
    result = _run(transcript, "cp1252")

    assert result.returncode == 0
    assert BEYOND_CP1252 in result.stdout.decode("utf-8")
