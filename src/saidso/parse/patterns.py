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
# The name may start lowercase ("morgan") - Teams shows whatever the guest typed.
DOCX_SPEAKER_LINE_RE = re.compile(
    r"^([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+){0,3})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*(.*)$"
)
# The same header alone on its line, as in a Teams transcript saved as .txt.
# The wide gap and empty tail keep "Meet me at 3:30" from matching.
TEAMS_TEXT_HEADER_RE = re.compile(
    r"^\s*[A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+){0,3}\s{2,}\d{1,2}:\d{2}(?::\d{2})?\s*$"
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

# Teams' copy-paste transcript (.txt): each turn is headed
#   Tara Zane                             <- name alone
#   0 minutes 29 seconds0:29              <- spoken + clock time, run together
#   Tara Zane 0 minutes 29 seconds        <- the header we key on
#   Mm.
#   TZ                                    <- next speaker's avatar initials
# Continuation turns carry only the third line. Gated on TEAMS_TXT_TIME_RE being
# present, since "wait 30 seconds" is ordinary dialogue anywhere else.
# A turn that starts on the minute drops the seconds: "19 minutes19:00".
_SPOKEN_TIME = (
    r"(?:\d+ hours?(?: \d+ minutes?)?(?: \d+ seconds?)?"
    r"|\d+ minutes?(?: \d+ seconds?)?"
    r"|\d+ seconds?)"
)
TEAMS_TXT_TIME_RE = re.compile(rf"^\s*{_SPOKEN_TIME}\d{{1,2}}:\d{{2}}(?::\d{{2}})?\s*$")
TEAMS_TXT_HEADER_RE = re.compile(rf"^\s*(?P<name>.+?)\s+{_SPOKEN_TIME}\s*$")
AVATAR_INITIALS_RE = re.compile(r"^\s*[A-Z]{1,3}\s*$")

# Tactiq's export (.txt): a "Meeting started / Duration / Participants" header,
# a "## Highlights" section quoting lines from the meeting, then "## Transcript"
# with "00:36 Jon Fisk: text" lines. Only the transcript section is dialogue -
# the highlights would duplicate it, and the header would be read as speakers.
TACTIQ_MARKER_RE = re.compile(r"^\s*(?:Meeting started:|\[View original transcript\]\(https://app\.tactiq\.io/)")
TACTIQ_TRANSCRIPT_RE = re.compile(r"^\s*\#{1,6}\s+Transcript\s*$", re.IGNORECASE)
# The extension announces itself into the call, sometimes twice on one line.
TACTIQ_PLUG_RE = re.compile(
    r"\s*Hi, I'm transcribing this call with my Tactiq AI Extension\.?\s*(?:https://tactiq\.io/\S*)?",
    re.IGNORECASE,
)

# Structure, not speech.
NOISE_RE = re.compile(r"^\s*(?:-{3,}|={3,}|\*{3,}|\|.*\||>\s*)\s*$")

# Meeting-platform chatter that isn't dialogue.
SYSTEM_RE = re.compile(
    r"^\s*(?:\*+\s*)?(?:recording (?:started|stopped)|transcription (?:started|stopped)|"
    r".{0,60}\b(?:joined|left) the meeting\b.{0,20}|"
    r".{0,60}\b(?:started|stopped) (?:transcription|recording)|"
    r"a?i-generated content may be incorrect\.?)(?:\s*\*+)?\s*$",
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
