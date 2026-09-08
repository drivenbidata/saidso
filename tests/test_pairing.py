"""A mic recording and a system recording of the same meeting are two halves of
one conversation. Live mode always knew that; transcribing files did not, and
produced two half-transcripts with nobody attributed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from saidso.pipeline import find_pairs


def _paths(*names):
    return [Path("/rec") / n for n in names]


def test_a_matching_mic_and_system_pair_up():
    pairs, singles = find_pairs(_paths("call_mic.wav", "call_system.wav"))
    assert [(m.name, s.name) for m, s in pairs] == [("call_mic.wav", "call_system.wav")]
    assert singles == []


def test_order_does_not_matter():
    pairs, _ = find_pairs(_paths("call_system.wav", "call_mic.wav"))
    assert pairs[0][0].name == "call_mic.wav"
    assert pairs[0][1].name == "call_system.wav"


@pytest.mark.parametrize(
    "mic,system",
    [
        ("m_mic.wav", "m_system.wav"),
        ("m-mic.wav", "m-system.wav"),
        ("m_mic.wav", "m_speakers.wav"),
        ("M_MIC.WAV", "M_SYSTEM.WAV"),
    ],
)
def test_the_suffixes_real_recorders_use(mic, system):
    pairs, singles = find_pairs(_paths(mic, system))
    assert len(pairs) == 1 and singles == []


def test_an_unmatched_half_is_left_alone():
    """A `_mic` with no `_system` is just a recording; guessing would be worse."""
    pairs, singles = find_pairs(_paths("lonely_mic.wav"))
    assert pairs == []
    assert [p.name for p in singles] == ["lonely_mic.wav"]


def test_ordinary_recordings_are_untouched():
    pairs, singles = find_pairs(_paths("standup.mp4", "review.m4a"))
    assert pairs == []
    assert len(singles) == 2


def test_several_meetings_pair_independently():
    pairs, singles = find_pairs(
        _paths("a_mic.wav", "b_system.wav", "a_system.wav", "b_mic.wav", "c.mp4")
    )
    assert {m.name for m, _ in pairs} == {"a_mic.wav", "b_mic.wav"}
    assert [p.name for p in singles] == ["c.mp4"]


def test_two_files_in_the_same_role_are_not_a_pair():
    """Same role twice means two recordings, not one meeting."""
    pairs, singles = find_pairs(_paths("x_mic.wav", "x_mic.mp3"))
    assert pairs == []
    assert len(singles) == 2


def test_same_name_in_different_folders_does_not_pair():
    pairs, singles = find_pairs([Path("/a/call_mic.wav"), Path("/b/call_system.wav")])
    assert pairs == []
    assert len(singles) == 2


def test_the_pair_transcript_is_named_from_the_shared_part(cfg, monkeypatch):
    """Not "Meeting mic": the title comes from the name without the role."""
    import saidso.pipeline as pipeline
    from saidso.models import Segment

    recordings = cfg.notes_dir / "rec"
    recordings.mkdir(parents=True)
    mic = recordings / "2026-08-27_0730_Weekly-Sync_mic.wav"
    system = recordings / "2026-08-27_0730_Weekly-Sync_system.wav"
    for p in (mic, system):
        p.write_bytes(b"\0" * 2048)

    def fake_merge(config, tracks, **kw):
        return pipeline.MergedTracks(
            segments=[
                Segment(0.0, 2.0, "Morning.", None if label == "system" else None)
                for label, _ in tracks
            ],
            duration=2.0,
            language="en",
        )

    monkeypatch.setattr(pipeline, "merge_tracks", fake_merge)
    outcome = pipeline.transcribe_pair(cfg, mic, system)

    assert outcome.kind == "paired"
    assert outcome.meta.title == "Weekly Sync"
    assert outcome.meta.source == f"{mic.name} + {system.name}"
    assert any("Combined two tracks" in n for n in outcome.notes)
