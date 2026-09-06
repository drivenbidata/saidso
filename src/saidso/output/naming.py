"""Filenames: slugs, templates, and claiming a path without racing.

Two properties are load-bearing and both come from the prototype's experience:

* The meeting date leads the filename. It is the first and only authoritative
  step in date resolution downstream — a batch of transcripts downloaded
  together share an mtime that is the *download* date, not the meeting date.
* Claiming a path is atomic, so two recorders finishing at once can't overwrite
  each other's transcript.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

DEFAULT_TEMPLATE = "{date}_{project}_{slug}"
MAX_SLUG = 80

# A date, optionally followed by a time, anywhere in a filename. Defined here
# and imported by routing so the two can never disagree about what part of a
# filename is a date.
DATE_IN_NAME = re.compile(
    r"(?<!\d)\d{4}[-_.]?\d{2}[-_.]?\d{2}(?:[T_ ]\d{2}[-_.]?\d{2}(?:[-_.]?\d{2})?)?(?!\d)"
)


def slugify(name: str, *, max_length: int = MAX_SLUG) -> str:
    """A filesystem-safe, readable token. Never empty."""
    name = re.sub(r"[^\w\s-]", "", name or "", flags=re.UNICODE).strip()
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:max_length] or "meeting"


def build_basename(
    *,
    title: str,
    when: dt.datetime | dt.date,
    project: str = "",
    template: str = DEFAULT_TEMPLATE,
) -> str:
    """Render a filename stem from the template, dropping empty fields cleanly."""
    date = when.date() if isinstance(when, dt.datetime) else when
    time = when.strftime("%H%M") if isinstance(when, dt.datetime) else ""
    stem = template.format(
        date=date.isoformat(),
        time=time,
        project=project or "",
        slug=slugify(title),
        title=slugify(title),
    )
    # An empty field leaves a doubled or trailing separator behind.
    stem = re.sub(r"[_-]{2,}", "_", stem).strip("_-")
    return stem or slugify(title)


def claim(directory: Path, basename: str, suffix: str = ".md") -> Path:
    """Create and return an unused path, atomically.

    The file is created empty so the name is taken the instant this returns;
    the caller overwrites it. Without this, two instances finishing within the
    same second both compute the same name and one transcript is lost.
    """
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        stem = basename if n == 1 else f"{basename}-{n}"
        candidate = directory / f"{stem}{suffix}"
        try:
            candidate.touch(exist_ok=False)
            return candidate
        except FileExistsError:
            n += 1
        if n > 999:
            raise OSError(f"Could not claim a filename for {basename!r} in {directory}")


def title_from_path(path: Path | str) -> str:
    """A readable meeting title from a filename.

    The date is stripped: it is already the leading element of the name saidso
    writes, and leaving it in the title produces "2026-09-02_acme_2026-09-02-
    Kickoff". Separators become spaces so the title reads as a title.
    """
    stem = DATE_IN_NAME.sub(" ", Path(path).stem)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -_")
    return stem or Path(path).stem
