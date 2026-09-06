"""Moving ticked items from Open to Completed, safely.

This is the one part of the tracker that runs unattended, so it is written to
fail closed. Every sweep is validated against the file it started from, and if
any check fails the original text is returned unchanged and the reason is
reported. A tracker that didn't get swept is a minor annoyance; a tracker that
got mangled loses work a person entered by hand.

The checks exist because a naive rewrite really does eat the blank line after
`## Open`, producing `## Open## [[first-meeting…` — found by simulating a
check-off before wiring any of this up.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .model import Block, Item, Tracker, parse


@dataclass(slots=True)
class SweepResult:
    text: str
    moved: list[str] = field(default_factory=list)
    dropped_headings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.moved) and not self.problems

    @property
    def ok(self) -> bool:
        return not self.problems


def _unchecked_texts(tracker: Tracker) -> list[str]:
    return [i.text for i in tracker.open_items() if not i.checked]


def sweep(text: str, *, today: dt.date | None = None) -> SweepResult:
    """Move every `- [x]` item out of Open and into Completed."""
    today = today or dt.date.today()
    before = parse(text)
    checked = before.checked_items()
    if not checked:
        return SweepResult(text=text)

    before_open = len(before.open_items())
    before_completed = before.completed_count()
    before_unchecked = _unchecked_texts(before)

    after = parse(text)  # a second, independent parse to mutate
    moved: list[str] = []
    dropped: list[str] = []
    new_completed: list[str] = []

    for block in after.open_blocks:
        keeping: list[Item] = []
        for item in block.items:
            if not item.checked:
                keeping.append(item)
                continue
            on = item.done_date or today.isoformat()
            new_completed.append(item.as_completed(block.attribution, on))
            moved.append(item.text)
        had_items = bool(block.items)
        block.items = keeping
        if had_items and not keeping and block.heading:
            dropped.append(block.heading)

    # A heading whose items are all done carries no information; drop it, unless
    # it had prose under it that someone wrote deliberately.
    after.open_blocks = [
        b for b in after.open_blocks if b.items or b.lines or not b.heading
    ]
    # Newest first, matching how new meetings are inserted.
    after.completed = new_completed + after.completed

    result = SweepResult(text=after.render(), moved=moved, dropped_headings=dropped)

    check = parse(result.text)
    n = len(moved)
    if len(check.open_items()) != before_open - n:
        result.problems.append(
            f"open count went from {before_open} to {len(check.open_items())}, expected "
            f"{before_open - n}"
        )
    if check.completed_count() != before_completed + n:
        result.problems.append(
            f"completed count went from {before_completed} to {check.completed_count()}, "
            f"expected {before_completed + n}"
        )
    if check.checked_items():
        result.problems.append(f"{len(check.checked_items())} ticked items left under Open")
    if _unchecked_texts(check) != before_unchecked:
        result.problems.append("unticked item text changed during the sweep")
    if before.has_open and "\n## Open\n\n" not in "\n" + result.text:
        result.problems.append("the blank line after '## Open' was lost")

    if result.problems:
        result.text = text  # fail closed: hand back exactly what came in
    return result


def add_meeting(
    text: str,
    *,
    heading: str,
    items: list[str],
    date: dt.date | None = None,
) -> str:
    """Insert a meeting and its items at the top of Open.

    Never touches Completed and never edits existing entries — an insertion and
    nothing else, so a hand-maintained tracker stays as its owner left it.
    """
    if not items:
        return text
    tracker = parse(text)
    suffix = f" — {date.isoformat()}" if date else ""
    block = Block(
        heading=f"## {heading}{suffix}",
        items=[Item(text=i, checked=False) for i in items],
    )
    tracker.add_block(block)
    return tracker.render()


def starter(title: str) -> str:
    """A new, empty tracker."""
    return (
        "---\n"
        "tags: [tracker]\n"
        f"updated: {dt.date.today().isoformat()}\n"
        "---\n"
        "\n"
        f"# {title} — Action Tracker\n"
        "\n"
        "## Open\n"
        "\n"
        "## Completed\n"
    )
