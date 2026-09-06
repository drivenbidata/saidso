"""Working out when a meeting actually happened.

The date is the frontmatter's load-bearing field and the filename's sort key,
and getting it wrong is quietly destructive: a batch of transcripts downloaded
together all carry the same modification time — the *download* date — so four
meetings weeks apart end up looking like one afternoon.

saidso resolves only the steps a program can be right about:

    1. a date in the filename          authoritative
    2. `recorded:` in the frontmatter  authoritative (saidso wrote it)
    3. the file's modification time    last resort, flagged as inferred

The remaining steps in the original ladder — a date or day-of-week spoken in
the dialogue, a reference to another meeting, the user simply saying — need
reading comprehension, and belong to the agent that reads the transcript. When
this module falls back to step 3 it says so, and the flag is carried into the
frontmatter as `date_inferred: true` so nothing downstream presents a guess as
a fact.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from .output import frontmatter as fm

# 2026-09-01, 2026_09_01, 20260901
_FILENAME_DATE = re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
_ISO_DATETIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?")

FILENAME = "filename"
FRONTMATTER = "frontmatter"
MTIME = "mtime"
GIVEN = "given"


@dataclass(frozen=True, slots=True)
class DateGuess:
    when: dt.datetime
    source: str

    @property
    def inferred(self) -> bool:
        """True when nothing authoritative stated the date."""
        return self.source == MTIME

    @property
    def explanation(self) -> str:
        return {
            FILENAME: "taken from the filename",
            FRONTMATTER: "taken from the transcript's own frontmatter",
            GIVEN: "given explicitly",
            MTIME: (
                "inferred from the file's modification time, which for a downloaded "
                "transcript is the download date, not the meeting date — please confirm"
            ),
        }.get(self.source, self.source)


def from_filename(path: Path | str) -> dt.datetime | None:
    m = _FILENAME_DATE.search(Path(path).stem)
    if not m:
        return None
    try:
        return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None  # 2026-13-45 and friends


def from_text(value: str) -> dt.datetime | None:
    m = _ISO_DATETIME.match(value.strip())
    if not m:
        return None
    try:
        return dt.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
        )
    except ValueError:
        return None


def resolve(
    path: Path | str | None = None,
    *,
    given: dt.datetime | dt.date | None = None,
    text: str | None = None,
) -> DateGuess:
    """Resolve a meeting date, reporting which step produced it."""
    if given is not None:
        when = given if isinstance(given, dt.datetime) else dt.datetime.combine(given, dt.time())
        return DateGuess(when, GIVEN)

    if path is not None and (when := from_filename(path)) is not None:
        return DateGuess(when, FILENAME)

    if text is None and path is not None and Path(path).suffix.lower() in (".md", ".markdown", ".txt"):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            text = None

    if text:
        meta = fm.loads(text)
        for key in ("recorded", "date", "started"):
            raw = meta.get(key)
            if isinstance(raw, str) and (when := from_text(raw)) is not None:
                return DateGuess(when, FRONTMATTER)

    if path is not None and Path(path).exists():
        return DateGuess(dt.datetime.fromtimestamp(Path(path).stat().st_mtime), MTIME)

    return DateGuess(dt.datetime.now(), GIVEN)
