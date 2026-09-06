"""Regexes for recognising transcript structure.

Ported from the prototype's parse_transcript.py. Every pattern here exists
because a real export broke without it, so they are worth keeping intact even
where they look over-general.
"""

from __future__ import annotations

import re

VTT_SPEAKER_RE = re.compile(r"<v\s+([^>]+?)>(.*?)</v>", re.IGNORECASE | re.DOTALL)
TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*$")

# Teams' DOCX export: "Ana Ruiz   0:01" then dialogue, or all on one line.
DOCX_SPEAKER_LINE_RE = re.compile(
    r"^([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*(.*)$"
)
DOCX_SPEAKER_ONLY_RE = re.compile(
    r"^([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
)

# A leading timestamp in any shape transcription tools emit:
#   [00:01:23]  (00:01:23)  00:01:23  0:01  [0:01:23.456]  <00:01:23>  00:01 --> 00:04
LEADING_TS_RE = re.compile(
    r"^\s*[\[\(<]?\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*(?:-->\s*"
    r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*)?[\]\)>]?\s*[-:]?\s*"
)

# Speaker prefix. Handles bold/italic markdown, list bullets, bracketed names:
#   **Ana Ruiz:** text     *Ana:* text     - Ana Ruiz: text
#   [Ana Ruiz]: text       ANA RUIZ: text  Ana Ruiz: text
SPEAKER_PREFIX_RE = re.compile(
    r"""^\s*
    (?:[-*+]\s+)?                      # optional list bullet
    (?:\*{1,2}|_{1,2})?                # optional bold/italic opener
    \[?                                # optional [
    (?P<name>[A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*){0,3})
    \]?                                # optional ]
    (?:\*{1,2}|_{1,2})?                # optional bold/italic closer
    \s*:\s*                            # the colon
    (?P<text>.*)$
    """,
    re.VERBOSE,
)

# Speaker alone on a line:  **Ana Ruiz**  or  _Ana Ruiz_
SPEAKER_HEADING_RE = re.compile(
    r"""^\s*
    (?:\*{1,2}|_{1,2})
    (?P<name>[A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*){0,3})
    (?:\*{1,2}|_{1,2})
    \s*:?\s*$
    """,
    re.VERBOSE,
)
# Speaker on its own line with a TRAILING timestamp, then dialogue below:
#   **Others** [00:00]     **Ana Ruiz** 0:01     _Dev_ [00:12:03]
# Emitted by earlier versions of the recorder. Without this the whole file
# degrades to one unattributed block, which is how six real transcripts lost
# their attribution silently.
SPEAKER_HEADING_TS_RE = re.compile(
    r"""^\s*
    (?:\*{1,2}|_{1,2})
    (?P<name>[A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*){0,3})
    (?:\*{1,2}|_{1,2})
    \s*[\[\(<]?\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*[\]\)>]?\s*:?\s*$
    """,
    re.VERBOSE,
)
# Same, without emphasis. The bracket is required here - "Name 0:01" alone is
# too close to ordinary dialogue to claim as a speaker line.
SPEAKER_BARE_TS_RE = re.compile(
    r"""^\s*
    (?P<name>[A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*){0,3})
    \s*[\[\(<]\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*[\]\)>]\s*:?\s*$
    """,
    re.VERBOSE,
)
SPEAKER_HEADING_HASH_RE = re.compile(
    r"^\s*\#{1,6}\s+(?P<name>[A-Za-z][\w'.\-]*(?:\s+[A-Za-z][\w'.\-]*){0,3})\s*:?\s*$"
)
ANY_HEADING_RE = re.compile(r"^\s*\#{1,6}\s+")

# Structure, not speech.
NOISE_RE = re.compile(r"^\s*(?:-{3,}|={3,}|\*{3,}|\|.*\||>\s*)\s*$")

# Meeting-platform chatter that isn't dialogue.
SYSTEM_RE = re.compile(
    r"^\s*(?:\*+\s*)?(?:recording (?:started|stopped)|transcription (?:started|stopped)|"
    r".{0,60}\b(?:joined|left) the meeting\b.{0,20})(?:\s*\*+)?\s*$",
    re.IGNORECASE,
)

FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)

# Words that look like a speaker name but are really section labels.
NOT_SPEAKERS = frozenset(
    {
        "note", "notes", "summary", "transcript", "attendees", "participants",
        "date", "time", "duration", "meeting", "topic", "topics", "agenda",
        "action items", "action", "actions", "decisions", "next steps",
        "warning", "error", "todo", "tip", "http", "https", "speaker", "title",
    }
)

UNATTRIBUTED = "(unattributed)"
