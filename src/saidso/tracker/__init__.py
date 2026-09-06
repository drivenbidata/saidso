"""Action tracking: the deterministic half.

saidso does not decide what an action item is — that is reading comprehension,
and belongs to whichever agent writes the meeting note. What saidso owns is
everything mechanical afterwards: inserting items, moving ticked ones into
Completed with the right date and attribution, dropping finished meetings, and
regenerating the index. Those are rules, not judgement, and rules belong in code
where they run the same way every time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..output.markdown import write_atomic
from . import index
from .index import ProjectStats
from .model import Block, Item, Tracker, parse
from .sweep import SweepResult, add_meeting, starter, sweep

__all__ = [
    "Block",
    "Item",
    "ProjectStats",
    "SweepResult",
    "SweepReport",
    "Tracker",
    "add_meeting",
    "add_to_project",
    "index",
    "parse",
    "starter",
    "sweep",
    "sweep_all",
]


@dataclass(slots=True)
class SweepReport:
    swept: dict[str, SweepResult] = field(default_factory=dict)
    index_path: Path | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def moved(self) -> int:
        return sum(len(r.moved) for r in self.swept.values())

    @property
    def ok(self) -> bool:
        return not self.problems


def _ensure_tracker(path: Path, title: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return starter(title)


def add_to_project(
    cfg: Config,
    project_key: str,
    *,
    heading: str,
    items: list[str],
    date: dt.date | None = None,
) -> Path:
    """Add a meeting's items to a project's tracker, creating it if needed."""
    project = cfg.project(project_key)
    path = cfg.notes_dir / project.tracker_path()
    text = _ensure_tracker(path, project.label)
    return write_atomic(path, add_meeting(text, heading=heading, items=items, date=date))


def sweep_all(cfg: Config, *, today: dt.date | None = None, dry_run: bool = False) -> SweepReport:
    """Sweep every project's tracker, then rebuild the index.

    A tracker that fails validation is left exactly as it was and reported; the
    other projects still get swept. One bad file must not block the rest.
    """
    report = SweepReport()
    for project in cfg.active_projects():
        path = cfg.notes_dir / project.tracker_path()
        if not path.exists():
            continue
        result = sweep(path.read_text(encoding="utf-8", errors="replace"), today=today)
        report.swept[project.key] = result
        if result.problems:
            report.problems += [f"{project.key}: {p}" for p in result.problems]
            continue
        if result.moved and not dry_run:
            write_atomic(path, result.text)

    if not dry_run:
        report.index_path = index.write(cfg, today=today)
    return report
