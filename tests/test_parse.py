"""The parser is the piece with the most real-world variation, so it carries
the most tests. Every shape here came from a transcript that actually existed.
"""
from __future__ import annotations

import pytest

from saidso.errors import ParseError
from saidso.parse import parse_file, parse_text


def test_bold_speaker_with_leading_timestamp():
    r = parse_text("[00:00:04] **Ana Ruiz:** Morning.\n[00:00:15] **Ben Okafor:** Hello.")
    assert [(u.speaker, u.text) for u in r.utterances] == [
        ("Ana Ruiz", "Morning."),
        ("Ben Okafor", "Hello."),
    ]


def test_trailing_timestamp_speaker_line():
    """The shape an earlier recorder emitted; missing it lost all attribution."""
    r = parse_text("**Others** [00:00]\nI was trying to find it.\n\n**Me** [00:09]\nHey, hold on.")
    assert [(u.speaker, u.text) for u in r.utterances] == [
        ("Others", "I was trying to find it."),
        ("Me", "Hey, hold on."),
    ]


def test_bare_name_with_bracketed_timestamp():
    r = parse_text("Ana Ruiz [0:01]\nGood morning.")
    assert r.utterances[0].speaker == "Ana Ruiz"


def test_heading_and_plain_and_bullet_speakers():
    r = parse_text("### Dana Silva\nDefinitions move.\n- Ben Okafor: Can you hear me?\nCass: Yes.")
    assert [u.speaker for u in r.utterances] == ["Dana Silva", "Ben Okafor", "Cass"]


def test_contiguous_turns_merge():
    r = parse_text("Cass: One.\nCass: Two.\nDev: Three.")
    assert len(r.utterances) == 2
    assert r.utterances[0].text == "One. Two."


def test_frontmatter_rules_tables_and_system_chatter_dropped():
    r = parse_text(
        "---\ntitle: X\n---\n\n# Heading\n\n---\n| a | b |\n"
        "Recording started\nAna Ruiz joined the meeting\nCass: Real content."
    )
    assert [(u.speaker, u.text) for u in r.utterances] == [("Cass", "Real content.")]


def test_section_labels_are_not_speakers():
    r = parse_text("Cass: Hello.\nAction items: none today.")
    assert [u.speaker for u in r.utterances] == ["Cass"]
    assert "none today" in r.utterances[0].text


def test_vtt_voice_tags():
    r = parse_text(
        "WEBVTT\n\n00:00:01.234 --> 00:00:04.567\n<v Ana Ruiz>Good morning.</v>\n", fmt="vtt"
    )
    assert [(u.speaker, u.text) for u in r.utterances] == [("Ana Ruiz", "Good morning.")]


def test_unattributed_fallback_keeps_content():
    r = parse_text("Just prose. No speakers anywhere.")
    assert not r.attributed
    assert "Just prose" in r.utterances[0].text


def test_speakers_are_first_appearance_order():
    r = parse_text("Dev: a\nCass: b\nDev: c")
    assert r.speakers == ["Dev", "Cass"]


def test_as_log_shape():
    r = parse_text("Cass: Hello there.")
    assert r.as_log() == "Cass: Hello there."


def test_missing_file_raises(tmp_path):
    with pytest.raises(ParseError):
        parse_file(tmp_path / "nope.vtt")


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ParseError):
        parse_file(p)
