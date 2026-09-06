from __future__ import annotations

import datetime as dt

from saidso import tracker
from saidso.tracker import index
from saidso.tracker.model import parse
from saidso.tracker.sweep import add_meeting, starter, sweep


def _tracker_with(items, heading="[[acme-sync-2026-09-01|Weekly Sync]]"):
    return add_meeting(starter("Acme"), heading=heading, items=items, date=dt.date(2026, 9, 1))


def test_add_inserts_newest_first_and_leaves_completed_alone():
    text = _tracker_with(["First thing"])
    text = add_meeting(text, heading="[[acme-standup-2026-09-02|Standup]]",
                       items=["Second thing"], date=dt.date(2026, 9, 2))
    order = [b.heading for b in parse(text).open_blocks]
    assert "Standup" in order[0] and "Weekly Sync" in order[1]
    assert parse(text).completed_count() == 0


def test_add_with_no_items_is_a_no_op():
    text = starter("Acme")
    assert add_meeting(text, heading="Empty", items=[]) == text


def test_sweep_moves_ticked_items_with_attribution():
    text = _tracker_with(["Send Rob the list · due: 2026-09-05", "Keep this open"])
    result = sweep(text.replace("- [ ] Send Rob", "- [x] Send Rob"), today=dt.date(2026, 9, 4))
    assert result.ok and len(result.moved) == 1
    after = parse(result.text)
    assert len(after.open_items()) == 1
    assert after.completed_count() == 1
    line = after.completed[0]
    assert "[[acme-sync-2026-09-01|Weekly Sync]]" in line
    assert "completed: 2026-09-04" in line
    assert "due:" not in line  # a due date is meaningless once done


def test_explicit_done_date_beats_the_sweep_date():
    text = _tracker_with(["Thing · done: 2026-09-03"])
    result = sweep(text.replace("- [ ] Thing", "- [x] Thing"), today=dt.date(2026, 9, 7))
    assert "completed: 2026-09-03" in result.text
    assert "done: 2026-09-03" not in result.text


def test_finished_meeting_heading_is_dropped():
    text = _tracker_with(["Only thing"])
    result = sweep(text.replace("- [ ]", "- [x]"), today=dt.date(2026, 9, 4))
    assert "Weekly Sync" not in [b.heading for b in parse(result.text).open_blocks]
    assert result.dropped_headings


def test_nothing_ticked_is_a_no_op():
    text = _tracker_with(["A", "B"])
    result = sweep(text, today=dt.date(2026, 9, 4))
    assert result.text == text and not result.moved


def test_blank_line_after_open_marker_survives():
    """A naive rewrite produces '## Open## [[first-meeting…' — the original bug."""
    text = _tracker_with(["A", "B"])
    result = sweep(text.replace("- [ ] A", "- [x] A"), today=dt.date(2026, 9, 4))
    assert "\n## Open\n\n" in result.text


def test_unticked_text_is_never_edited():
    text = _tracker_with(["Ticked", "Left alone · with · separators"])
    result = sweep(text.replace("- [ ] Ticked", "- [x] Ticked"), today=dt.date(2026, 9, 4))
    assert "- [ ] Left alone · with · separators" in result.text


def test_a_mangled_rewrite_is_refused_and_the_file_is_returned_unchanged(monkeypatch):
    """Fail closed: a sweep that doesn't validate must not reach disk."""
    from saidso.tracker import model

    text = _tracker_with(["Thing"]).replace("- [ ] Thing", "- [x] Thing")
    monkeypatch.setattr(model.Tracker, "render", lambda self: "## Open\n\n## Completed\n")
    result = sweep(text, today=dt.date(2026, 9, 4))
    assert not result.ok
    assert result.problems
    assert result.text == text


def test_sweep_all_writes_and_rebuilds_the_index(cfg):
    path = cfg.notes_dir / cfg.project("acme").tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_tracker_with(["A", "B"]).replace("- [ ] A", "- [x] A"), encoding="utf-8")

    report = tracker.sweep_all(cfg, today=dt.date(2026, 9, 4))
    assert report.ok and report.moved == 1
    assert "completed: 2026-09-04" in path.read_text(encoding="utf-8")

    body = cfg.index_path.read_text(encoding="utf-8")
    assert "Acme Corp" in body
    assert "Retired" not in body  # inactive projects stay out of the index


def test_dry_run_changes_nothing_on_disk(cfg):
    path = cfg.notes_dir / cfg.project("acme").tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    original = _tracker_with(["A"]).replace("- [ ] A", "- [x] A")
    path.write_text(original, encoding="utf-8")

    report = tracker.sweep_all(cfg, today=dt.date(2026, 9, 4), dry_run=True)
    assert report.moved == 1
    assert path.read_text(encoding="utf-8") == original


def test_index_reports_missing_trackers_without_failing(cfg):
    stats = index.collect(cfg)
    assert {s.key for s in stats} == {"acme", "Orbit8", "general"}
    assert all(not s.exists for s in stats)


def test_obsidian_flavor_uses_wiki_links(cfg):
    from dataclasses import replace

    from saidso.config import OutputSettings

    obsidian = replace(cfg, output=OutputSettings(flavor="obsidian"))
    body = index.render(index.collect(obsidian), flavor="obsidian")
    assert "acme/Tracker" in body
