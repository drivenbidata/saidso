"""The root tracker index: counts per project, and nothing else.

The index holds no items. It is regenerated wholesale on every run, so anything
written into it by hand is lost — which is exactly why it must never be a place
where state lives. Each project's own Tracker.md is the source of truth.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..output import frontmatter as fm
from ..output.markdown import write_atomic
from .model import parse


@dataclass(frozen=True, slots=True)
class ProjectStats:
    key: str
    label: str
    tracker: str  # path relative to notes_dir
    open_items: int = 0
    meetings: int = 0
    completed: int = 0
    exists: bool = True


def collect(cfg: Config) -> list[ProjectStats]:
    stats: list[ProjectStats] = []
    for project in cfg.active_projects():
        rel = project.tracker_path()
        path = cfg.notes_dir / rel
        if not path.exists():
            stats.append(ProjectStats(project.key, project.label, rel, exists=False))
            continue
        tracker = parse(path.read_text(encoding="utf-8", errors="replace"))
        stats.append(
            ProjectStats(
                key=project.key,
                label=project.label,
                tracker=rel,
                open_items=len(tracker.open_items()),
                meetings=tracker.meeting_count(),
                completed=tracker.completed_count(),
            )
        )
    return stats


def _link(rel: str, flavor: str) -> str:
    if flavor == "obsidian":
        # Obsidian resolves wiki-links by basename, so the stem is the target.
        return f"[[{Path(rel).with_suffix('').as_posix()}|{rel}]]"
    return f"[{rel}]({rel})"


def render(stats: list[ProjectStats], *, flavor: str = "plain", today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    lines = [
        fm.dumps({"tags": ["tracker", "index"], "updated": today}),
        "",
        "# Action Trackers — Index",
        "",
        "*Index only — this file holds no items, and is regenerated in full on every"
        " sweep. Tick things off in the per-project trackers below.*",
        "",
        "| Project | Tracker | Open | Meetings | Completed |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for s in stats:
        link = _link(s.tracker, flavor) if s.exists else f"`{s.tracker}` (not created yet)"
        lines.append(f"| **{s.label}** | {link} | {s.open_items} | {s.meetings} | {s.completed} |")

    total_open = sum(s.open_items for s in stats)
    total_done = sum(s.completed for s in stats)
    lines += [
        "",
        f"{total_open} open across {len(stats)} project(s); {total_done} completed.",
        "",
    ]
    return "\n".join(lines)


def write(cfg: Config, *, today: dt.date | None = None) -> Path:
    stats = collect(cfg)
    return write_atomic(cfg.index_path, render(stats, flavor=cfg.output.flavor, today=today))
