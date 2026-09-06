"""YAML frontmatter, written and read without a YAML dependency.

Frontmatter is the most important part of a transcript file: it is what an
agent filters on, what routing reads, and what survives when the dialogue is
too long to hold. It is treated as part of the output contract, not decoration.

The subset handled here is deliberately small — scalars, inline lists, block
lists — which is everything saidso writes and everything real transcript
exports carry. Anything richer is left as a string rather than guessed at. If
that ever stops being enough, this becomes a thin wrapper over PyYAML; until
then the core install stays dependency-free.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

DELIMITER = "---"

_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-/@()']*$")
# Strings that YAML would read back as something other than a string.
_AMBIGUOUS = re.compile(
    r"^(?:true|false|yes|no|on|off|null|~|-?\d+(?:\.\d+)?|\d{4}-\d{2}-\d{2}.*)$",
    re.IGNORECASE,
)


def quote(value: str) -> str:
    """Emit a string that reads back as the same string."""
    if value == "":
        return '""'
    if _PLAIN_SAFE.match(value) and not _AMBIGUOUS.match(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, dt.date):
        return value.isoformat()
    return quote(str(value))


def dumps(data: dict[str, Any], *, block_lists: tuple[str, ...] = ()) -> str:
    """Render a frontmatter block, delimiters included.

    Keys with an empty value are dropped: an absent field is honest, whereas
    `workstream: ""` invites a reader to treat the empty string as meaningful.
    Names in `block_lists` are written one-per-line instead of inline.
    """
    lines = [DELIMITER]
    for key, value in data.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            items = [str(v) for v in value if str(v).strip()]
            if not items:
                continue
            if key in block_lists:
                lines.append(f"{key}:")
                lines.extend(f"  - {quote(v)}" for v in items)
            else:
                lines.append(f"{key}: [{', '.join(quote(v) for v in items)}]")
        else:
            lines.append(f"{key}: {_scalar(value)}")
    lines.append(DELIMITER)
    return "\n".join(lines)


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        body = raw[1:-1]
        if raw[0] == '"':
            return body.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        return body
    return raw


def loads(text: str) -> dict[str, Any]:
    """Read a leading frontmatter block. Returns {} when there isn't one.

    Values come back as strings or lists of strings — no type coercion, because
    a caller that wants a date knows it wants a date, and guessing is how
    "2026-09-01" becomes a datetime in one code path and a string in another.
    """
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        return {}

    out: dict[str, Any] = {}
    key: str | None = None
    block: list[str] = []

    def flush() -> None:
        nonlocal key, block
        if key is not None and block:
            out[key] = block
        key, block = None, []

    for line in lines[1:]:
        if line.strip() == DELIMITER:
            flush()
            return out
        if not line.strip():
            continue

        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key is not None:
            block.append(_unquote(item.group(1)))
            continue

        pair = re.match(r"^([A-Za-z_][\w.\-]*)\s*:\s*(.*)$", line)
        if not pair:
            continue
        flush()
        name, raw = pair.group(1), pair.group(2).strip()
        if raw == "":
            key = name  # a block list may follow
            out.setdefault(name, "")
            continue
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            out[name] = [_unquote(p) for p in _split_inline(inner)] if inner else []
        else:
            out[name] = _unquote(raw)

    flush()
    return out  # unterminated block: return what was readable


def _split_inline(inner: str) -> list[str]:
    """Split an inline list on commas that aren't inside quotes."""
    parts, buf, quoting = [], [], ""
    for ch in inner:
        if quoting:
            buf.append(ch)
            if ch == quoting:
                quoting = ""
        elif ch in "\"'":
            quoting = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def split(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter, body) for a document."""
    data = loads(text)
    if not data:
        return {}, text
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == DELIMITER:
            return data, "".join(lines[i + 1:])
    return data, ""
