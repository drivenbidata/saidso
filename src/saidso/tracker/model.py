"""Reading and writing a Tracker.md without disturbing anything else in it.

A tracker is a file a person edits by hand — ticking boxes in an editor, adding
a note beside an item, reordering things. So this parser is deliberately
conservative: it recognises the two section markers and the checkbox lines, and
treats every other line as opaque text to be preserved byte for byte.

Layout:

    ## Open
    ## [[note-basename|Meeting Title]] — 2026-09-01
    - [ ] The specific thing to do · due: TBD

    ## Completed
    - [x] The thing · [[note-basename|Meeting Title]] · completed: 2026-09-02

Meeting headings are `##`, the same level as the section markers, which is
inherited from the original format. The markers are therefore matched by name
and every other `##` is a meeting heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OPEN = "Open"
COMPLETED = "Completed"

SECTION_RE = re.compile(r"^##\s+(Open|Completed)\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^##\s+(?P<body>.+?)\s*$")
ITEM_RE = re.compile(r"^(?P<indent>\s*)[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<text>.*?)\s*$")

# "· due: 2026-09-05" / "· done: 2026-09-03" — the metadata suffixes on an item.
DUE_RE = re.compile(r"\s*[·|]\s*due:\s*\S+\s*$", re.IGNORECASE)
DONE_RE = re.compile(r"\s*[·|]\s*done:\s*(\d{4}-\d{2}-\d{2})\s*$", re.IGNORECASE)
# Trailing "— 2026-09-01" on a meeting heading.
HEADING_DATE_RE = re.compile(r"\s*[—-]\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(slots=True)
class Item:
    text: str
    checked: bool
    indent: str = ""

    @property
    def done_date(self) -> str | None:
        """An explicit `· done: YYYY-MM-DD`, which wins over the sweep date.

        Ticks are noticed when the sweep next runs, so a Friday check-off would
        otherwise be recorded as Monday. Writing the date by hand fixes it.
        """
        m = DONE_RE.search(self.text)
        return m.group(1) if m else None

    def render(self) -> str:
        return f"{self.indent}- [{'x' if self.checked else ' '}] {self.text}"

    def as_completed(self, attribution: str, on: str) -> str:
        """The standalone form kept in Completed — it must read without its heading."""
        text = DONE_RE.sub("", DUE_RE.sub("", self.text)).strip()
        parts = [text]
        if attribution:
            parts.append(attribution)
        parts.append(f"completed: {on}")
        return "- [x] " + " · ".join(parts)


@dataclass(slots=True)
class Block:
    """A meeting heading and the items under it."""

    heading: str  # the full "## ..." line, or "" for items with no heading
    lines: list[str] = field(default_factory=list)  # non-item lines, in order
    items: list[Item] = field(default_factory=list)

    @property
    def attribution(self) -> str:
        """The link part of the heading, for stamping onto a completed item."""
        if not self.heading:
            return ""
        m = HEADING_RE.match(self.heading)
        body = m.group("body") if m else self.heading.lstrip("# ").strip()
        return HEADING_DATE_RE.sub("", body).strip()

    def render(self) -> list[str]:
        out: list[str] = []
        if self.heading:
            out.append(self.heading)
        out.extend(self.lines)
        out.extend(i.render() for i in self.items)
        return out


@dataclass(slots=True)
class Tracker:
    head: list[str] = field(default_factory=list)  # everything before "## Open"
    open_blocks: list[Block] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)  # raw lines, newest first
    has_open: bool = False
    has_completed: bool = False

    # ------------------------------------------------------------ counts

    def open_items(self) -> list[Item]:
        return [i for b in self.open_blocks for i in b.items]

    def checked_items(self) -> list[Item]:
        return [i for i in self.open_items() if i.checked]

    def completed_count(self) -> int:
        return sum(1 for line in self.completed if ITEM_RE.match(line))

    def meeting_count(self) -> int:
        return sum(1 for b in self.open_blocks if b.heading)

    # ------------------------------------------------------------ mutation

    def add_block(self, block: Block) -> None:
        """Insert a meeting at the top of Open, so newest reads first."""
        self.open_blocks.insert(0, block)
        self.has_open = True

    # ------------------------------------------------------------ rendering

    def render(self) -> str:
        out: list[str] = list(self.head)
        while out and not out[-1].strip():
            out.pop()

        if self.has_open or self.open_blocks:
            out += ["", f"## {OPEN}", ""]
            for block in self.open_blocks:
                out += block.render()
                out.append("")
            while out and not out[-1].strip():
                out.pop()

        if self.has_completed or self.completed:
            out += ["", f"## {COMPLETED}", ""]
            out += self.completed
            while out and not out[-1].strip():
                out.pop()

        return "\n".join(out).lstrip("\n") + "\n"


def parse(text: str) -> Tracker:
    tracker = Tracker()
    section: str | None = None
    block: Block | None = None

    def close() -> None:
        nonlocal block
        if block is not None:
            while block.lines and not block.lines[-1].strip():
                block.lines.pop()
            tracker.open_blocks.append(block)
            block = None

    for raw in text.splitlines():
        line = raw.rstrip("\n")

        marker = SECTION_RE.match(line)
        if marker:
            close()
            name = marker.group(1).lower()
            section = OPEN if name == "open" else COMPLETED
            if section == OPEN:
                tracker.has_open = True
            else:
                tracker.has_completed = True
            continue

        if section is None:
            tracker.head.append(line)
            continue

        if section == COMPLETED:
            if line.strip():
                tracker.completed.append(line)
            continue

        if HEADING_RE.match(line):
            close()
            block = Block(heading=line)
            continue

        item = ITEM_RE.match(line)
        if item:
            if block is None:
                block = Block(heading="")
            block.items.append(
                Item(
                    text=item.group("text"),
                    checked=item.group("mark").lower() == "x",
                    indent=item.group("indent"),
                )
            )
            continue

        if block is None:
            if line.strip():
                block = Block(heading="")
                block.lines.append(line)
        else:
            block.lines.append(line)

    close()
    return tracker
