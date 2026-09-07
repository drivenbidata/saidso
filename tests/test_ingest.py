"""Ingest is the third way material arrives: a transcript someone else's tool
already produced. It needs no model, so all of this runs anywhere.
"""
from __future__ import annotations

import datetime as dt

import pytest

from saidso.errors import SaidsoError
from saidso.output import frontmatter as fm
from saidso.pipeline import ingest_file

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Ana Ruiz>Morning everyone, let's get going.</v>

00:00:05.000 --> 00:00:09.000
<v Ben Okafor>I have an update on the bronze tables.</v>
"""


def _vtt(tmp_path, name="2026-09-01_Weekly-Sync.vtt", body=VTT):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_an_export_lands_in_the_inbox_with_full_frontmatter(cfg, tmp_path):
    outcome = ingest_file(cfg, _vtt(tmp_path))

    assert outcome.transcript.parent == cfg.inbox_dir
    assert outcome.kind == "ingested"
    assert outcome.segments == 2

    meta, body = fm.split(outcome.transcript.read_text(encoding="utf-8"))
    assert meta["title"] == "Weekly Sync"
    assert meta["date"] == "2026-09-01"
    assert meta["project"] == "general"
    assert meta["speakers"] == ["Ana Ruiz", "Ben Okafor"]
    assert meta["source"] == "2026-09-01_Weekly-Sync.vtt"
    assert "**Ana Ruiz:** Morning everyone, let's get going." in body


def test_it_is_indistinguishable_downstream_from_a_recorded_transcript(cfg, tmp_path):
    """Routing, agents and search must not care where a transcript came from."""
    meta = fm.loads(ingest_file(cfg, _vtt(tmp_path)).transcript.read_text(encoding="utf-8"))
    for field in ("title", "date", "project", "source", "speakers", "generator"):
        assert field in meta, field


def test_no_timestamps_are_invented(cfg, tmp_path):
    """Cue times describe cue boundaries, not turns. Better absent than wrong."""
    body = ingest_file(cfg, _vtt(tmp_path)).transcript.read_text(encoding="utf-8")
    assert "[00:00:" not in body


def test_the_original_file_is_left_alone(cfg, tmp_path):
    source = _vtt(tmp_path)
    before = source.read_text(encoding="utf-8")
    ingest_file(cfg, source)
    assert source.exists() and source.read_text(encoding="utf-8") == before


def test_an_explicit_project_wins(cfg, tmp_path):
    assert ingest_file(cfg, _vtt(tmp_path), project="acme").project == "acme"


def test_a_project_token_in_the_filename_routes(cfg, tmp_path):
    outcome = ingest_file(cfg, _vtt(tmp_path, "acme - Weekly Sync - 2026-09-01.vtt"))
    assert outcome.project == "acme"


def test_a_given_date_is_not_treated_as_a_guess(cfg, tmp_path):
    outcome = ingest_file(cfg, _vtt(tmp_path, "sync.vtt"), when=dt.datetime(2026, 8, 20))
    assert outcome.meta.date == dt.date(2026, 8, 20)
    assert not outcome.meta.date_inferred
    assert "date_inferred" not in outcome.transcript.read_text(encoding="utf-8")


def test_a_date_only_from_mtime_is_flagged_and_explained(cfg, tmp_path):
    outcome = ingest_file(cfg, _vtt(tmp_path, "sync.vtt"))
    assert outcome.meta.date_inferred
    assert any("download date" in n for n in outcome.notes)
    assert "date_inferred: true" in outcome.transcript.read_text(encoding="utf-8")


def test_a_source_with_no_speakers_is_kept_and_said_so(cfg, tmp_path):
    source = tmp_path / "recap.txt"
    source.write_text("Topics discussed\nDeployment of v2.4 to staging.\n", encoding="utf-8")
    outcome = ingest_file(cfg, source)
    assert outcome.transcript.exists()
    assert any("nothing can be attributed" in n for n in outcome.notes)


def test_frontmatter_in_the_source_can_name_the_project(cfg, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("---\nproject: acme\n---\nAna Ruiz: Hello.\n", encoding="utf-8")
    assert ingest_file(cfg, source).project == "acme"


def test_two_ingests_of_the_same_file_do_not_overwrite(cfg, tmp_path):
    source = _vtt(tmp_path)
    first = ingest_file(cfg, source).transcript
    second = ingest_file(cfg, source).transcript
    assert first != second and first.exists() and second.exists()


def test_a_missing_file_is_reported_not_swallowed(cfg, tmp_path):
    with pytest.raises(SaidsoError, match="No such transcript"):
        ingest_file(cfg, tmp_path / "nope.vtt")


def test_a_media_file_sent_to_transcribe_points_at_ingest(cfg, tmp_path):
    """The error that used to name a command that did not exist."""
    from saidso.pipeline import transcribe_file

    source = tmp_path / "notes.vtt"
    source.write_text(VTT, encoding="utf-8")
    with pytest.raises(SaidsoError, match="saidso ingest"):
        transcribe_file(cfg, source)
