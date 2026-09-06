from __future__ import annotations

import datetime as dt

import pytest

from saidso.dating import resolve as resolve_date
from saidso.errors import UnknownProject
from saidso.models import Segment, TranscriptMeta
from saidso.output import frontmatter as fm
from saidso.output import routing
from saidso.output.markdown import render_transcript, write_atomic
from saidso.output.naming import build_basename, claim, slugify, title_from_path

# ---------------------------------------------------------------- frontmatter

@pytest.mark.parametrize("value", ["yes", "no", "true", "2026", "01:06:20", "2026-09-01"])
def test_ambiguous_strings_survive_a_round_trip(value):
    """Without quoting these read back as bools, ints or dates."""
    assert fm.loads(fm.dumps({"k": value}))["k"] == value


def test_empty_values_are_dropped_not_written_blank():
    out = fm.loads(fm.dumps({"a": "x", "b": "", "c": [], "d": None}))
    assert out == {"a": "x"}


def test_block_and_inline_lists():
    text = fm.dumps({"speakers": ["A", "B"], "participants": ["x@y"]}, block_lists=("participants",))
    assert "speakers: [A, B]" in text
    assert "  - x@y" in text
    assert fm.loads(text)["participants"] == ["x@y"]


def test_split_returns_body():
    meta, body = fm.split("---\na: 1\n---\nbody line\n")
    assert meta["a"] == "1"
    assert body.strip() == "body line"


def test_no_frontmatter_is_empty_not_an_error():
    assert fm.loads("# Heading\ntext") == {}


# ---------------------------------------------------------------- naming

def test_slugify_strips_punctuation_and_collapses():
    assert slugify("Q3 Planning: Northwind / Legacy -> BI!!") == "Q3-Planning-Northwind-Legacy-BI"


def test_slugify_never_empty():
    assert slugify("///") == "meeting"


def test_basename_drops_empty_project_without_double_separator():
    when = dt.datetime(2026, 9, 1, 15, 6)
    assert build_basename(title="Weekly Sync", when=when, project="") == "2026-09-01_Weekly-Sync"


def test_title_from_path_strips_the_date():
    assert title_from_path("2026-09-02_Orbit8-Kickoff.wav") == "Orbit8 Kickoff"


def test_claim_is_atomic_and_never_reuses(tmp_path):
    names = [claim(tmp_path, "x").name for _ in range(3)]
    assert names == ["x.md", "x-2.md", "x-3.md"]


def test_write_atomic_leaves_no_temp_files(tmp_path):
    target = tmp_path / "t.md"
    write_atomic(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert [p.name for p in tmp_path.iterdir()] == ["t.md"]


# ---------------------------------------------------------------- routing

def test_leading_project_token_routes(cfg):
    assert routing.resolve(cfg, path="acme - Weekly Sync - 2026-09-01.md").project.key == "acme"


def test_saidso_own_filename_shape_routes(cfg):
    """{date}_{project}_{slug} — the name saidso writes itself."""
    assert routing.resolve(cfg, path="2026-09-01_Orbit8_Weekly-Sync.md").project.key == "Orbit8"


def test_case_insensitive_match_is_noted(cfg):
    route = routing.resolve(cfg, path="orbit8-standup-2026-09-01.md")
    assert route.project.key == "Orbit8"
    assert "ignoring case" in route.note


def test_near_miss_refuses_rather_than_guessing(cfg):
    with pytest.raises(UnknownProject, match="very close"):
        routing.resolve(cfg, path="Orbit9 - Standup - 2026-09-01.md")


def test_ordinary_title_falls_back_to_default_quietly(cfg):
    route = routing.resolve(cfg, path="Client Services Dashboard V1.vtt")
    assert route.project.key == "general"
    assert not route.confident


def test_precedence_explicit_over_frontmatter_over_filename(cfg):
    assert routing.resolve(cfg, path="2026-09-01_Orbit8_x.md", meta={"project": "acme"}).project.key == "acme"
    assert routing.resolve(cfg, path="2026-09-01_Orbit8_x.md", meta={"project": "acme"},
                           explicit="general").project.key == "general"


def test_unknown_explicit_project_raises(cfg):
    with pytest.raises(UnknownProject):
        routing.resolve(cfg, explicit="nope")


# ---------------------------------------------------------------- dating

def test_filename_date_wins_and_is_not_inferred(tmp_path):
    p = tmp_path / "2026-09-01_sync.md"
    p.write_text("x", encoding="utf-8")
    guess = resolve_date(p)
    assert guess.when.date() == dt.date(2026, 9, 1)
    assert guess.source == "filename"
    assert not guess.inferred


def test_frontmatter_recorded_used_when_filename_has_no_date(tmp_path):
    p = tmp_path / "sync.md"
    p.write_text("---\nrecorded: 2026-08-20T14:00:00\n---\nCass: hi", encoding="utf-8")
    guess = resolve_date(p)
    assert guess.when.date() == dt.date(2026, 8, 20)
    assert guess.source == "frontmatter"


def test_mtime_is_last_resort_and_flagged(tmp_path):
    p = tmp_path / "sync.vtt"
    p.write_text("x", encoding="utf-8")
    guess = resolve_date(p)
    assert guess.source == "mtime"
    assert guess.inferred
    assert "download date" in guess.explanation


def test_impossible_filename_date_is_ignored(tmp_path):
    p = tmp_path / "2026-13-45_sync.vtt"
    p.write_text("x", encoding="utf-8")
    assert resolve_date(p).source == "mtime"


# ---------------------------------------------------------------- rendering

def _meta(**kw):
    base = {"title": "Weekly Sync", "when": dt.datetime(2026, 9, 1, 15, 6),
            "source": "live recording", "project": "acme", "date_source": "recorded"}
    return TranscriptMeta(**{**base, **kw})


def test_transcript_shape_is_one_line_per_turn():
    segs = [Segment(4.0, 9.0, " Morning.  ", "Ana Ruiz"), Segment(3625.0, 3630.0, "Bye.", "Dev")]
    body = render_transcript(segs, _meta())
    assert "[00:00:04] **Ana Ruiz:** Morning." in body
    assert "[01:00:25] **Dev:** Bye." in body


def test_inferred_date_carries_flag_and_a_visible_caveat():
    body = render_transcript([Segment(0, 1, "hi", "Cass")], _meta(date_source="mtime"))
    assert "date_inferred: true" in body
    assert "*Date 2026-09-01 was inferred" in body


def test_confident_date_carries_no_caveat():
    body = render_transcript([Segment(0, 1, "hi", "Cass")], _meta(date_source="filename"))
    assert "date_inferred" not in body
    assert "was inferred" not in body


def test_speakers_are_derived_into_frontmatter():
    segs = [Segment(0, 1, "a", "Cass"), Segment(1, 2, "b", "Dev"), Segment(2, 3, "c", "Cass")]
    assert "speakers: [Cass, Dev]" in render_transcript(segs, _meta())
