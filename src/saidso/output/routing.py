"""Deciding which project a transcript belongs to.

Order of precedence, first hit wins:

1. An explicit choice (a CLI flag, the desktop dropdown).
2. `project:` in the transcript's own frontmatter — saidso writes this itself.
3. A project key leading the filename, which is how transcripts exported from
   a meeting platform get routed without editing them.
4. The configured default.

The rule worth understanding is step 3's near miss. A filename token that
*nearly* matches a key — `Orbit9` for `Orbit8` — stops the run and asks instead
of falling through to the default. Misfiling a client's meeting is expensive
precisely because nobody notices; a failed run is noticed immediately. An
unrecognisable token is not a near miss and routes to the default quietly,
because most filenames simply don't carry a project at all.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config, Project
from ..errors import UnknownProject
from .naming import DATE_IN_NAME

NEAR_MISS_CUTOFF = 0.8
MIN_TOKEN = 3
_SPLIT = re.compile(r"[\s_\-]+")

EXPLICIT = "explicit"
FRONTMATTER = "frontmatter"
FILENAME = "filename"
DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class Route:
    project: Project
    reason: str
    note: str = ""

    @property
    def confident(self) -> bool:
        return self.reason != DEFAULT


def filename_tokens(path: Path | str, limit: int = 2) -> list[str]:
    """Leading filename tokens that could be a project key.

    Dates are removed from the stem *before* tokenising, not skipped after:
    splitting "2026-09-01_acme_sync" on separators first turns the date into
    three tokens and pushes the real project token out of range.
    """
    stem = DATE_IN_NAME.sub(" ", Path(path).stem)
    return [t for t in _SPLIT.split(stem) if t][:limit]


def match_token(cfg: Config, token: str) -> tuple[Project | None, str]:
    """Match one token against the project list. Returns (project, note)."""
    if len(token) < MIN_TOKEN:
        return None, ""

    for p in cfg.projects:
        if p.key == token:
            return p, ""

    lowered = token.lower()
    for p in cfg.projects:
        if p.key.lower() == lowered:
            return p, f"filename says {token!r}, matched project {p.key!r} ignoring case"

    keys = [p.key for p in cfg.projects]
    close = difflib.get_close_matches(lowered, [k.lower() for k in keys], n=1, cutoff=NEAR_MISS_CUTOFF)
    if close:
        actual = next(k for k in keys if k.lower() == close[0])
        raise UnknownProject(
            f"Filename starts with {token!r}, which isn't a project but is very close "
            f"to {actual!r}.\n"
            f"Refusing to guess — a misfiled meeting is hard to notice later.\n"
            f"Rename the file, or say which you meant with --project."
        )
    return None, ""


def resolve(
    cfg: Config,
    *,
    explicit: str | None = None,
    path: Path | str | None = None,
    meta: dict[str, Any] | None = None,
) -> Route:
    """Work out the destination project for a transcript."""
    if explicit:
        return Route(cfg.project(explicit), EXPLICIT)

    if meta:
        declared = str(meta.get("project") or "").strip()
        if declared:
            return Route(cfg.project(declared), FRONTMATTER)

    if path is not None:
        for token in filename_tokens(path):
            project, note = match_token(cfg, token)
            if project is not None:
                return Route(project, FILENAME, note)

    project = cfg.project(cfg.default_project)
    return Route(
        project,
        DEFAULT,
        f"nothing identified a project, so this went to the default ({project.key})",
    )
