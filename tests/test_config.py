from __future__ import annotations

import pytest

from saidso import config as config_mod
from saidso.errors import ConfigError, UnknownProject


def test_starter_round_trips_through_toml(tmp_path):
    cfg = config_mod.starter(notes_dir=tmp_path / "notes", speaker_name="Javi Gold")
    target = cfg.save(tmp_path / "config.toml")
    assert config_mod.load(target).to_dict() == cfg.to_dict()


def test_load_without_create_explains_how_to_fix(tmp_path):
    with pytest.raises(ConfigError, match="saidso init"):
        config_mod.load(tmp_path / "missing.toml")


def test_load_with_create_writes_a_starter(tmp_path):
    cfg = config_mod.load(tmp_path / "config.toml", create=True)
    assert (tmp_path / "config.toml").exists()
    assert cfg.project("general").folder == "general"


def test_invalid_toml_names_the_file(tmp_path):
    bad = tmp_path / "config.toml"
    bad.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        config_mod.load(bad)


def test_a_future_config_version_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="Upgrade saidso"):
        config_mod.from_dict({"version": 99})


@pytest.mark.parametrize("key", ["bad key", "a/b", "c\\d", "x:y"])
def test_keys_with_separators_or_spaces_are_rejected(key):
    with pytest.raises(ConfigError, match="filenames"):
        config_mod.from_dict({"projects": [{"key": key}]})


def test_a_relative_folder_may_not_escape_the_notes_directory():
    with pytest.raises(ConfigError, match="may not escape"):
        config_mod.from_dict({"projects": [{"key": "esc", "folder": "../elsewhere"}]})


def test_an_absolute_folder_keeps_a_project_in_its_own_vault(tmp_path):
    """Legacy notes that already live somewhere shouldn't have to move."""
    elsewhere = tmp_path / "legacy" / "acme"
    cfg = config_mod.from_dict(
        {
            "notes_dir": str(tmp_path / "notes"),
            "projects": [{"key": "acme", "folder": str(elsewhere)}],
        }
    )
    assert cfg.project("acme").is_external
    assert cfg.project_dir("acme") == elsewhere
    assert cfg.tracker_path("acme") == elsewhere / "Tracker.md"


def test_an_absolute_folder_still_may_not_contain_dotdot(tmp_path):
    escaping = str(tmp_path / "legacy" / ".." / "acme")
    with pytest.raises(ConfigError, match="may not escape"):
        config_mod.from_dict({"projects": [{"key": "acme", "folder": escaping}]})


def test_the_tracker_index_may_be_absolute(tmp_path):
    """So the index can sit beside external notes, not beside the config."""
    elsewhere = tmp_path / "legacy" / "Tracker.md"
    cfg = config_mod.from_dict(
        {"notes_dir": str(tmp_path / "notes"), "tracker": {"index": str(elsewhere)}}
    )
    assert cfg.index_path == elsewhere


def test_the_tracker_index_may_not_contain_dotdot():
    with pytest.raises(ConfigError, match="may not escape"):
        config_mod.from_dict({"tracker": {"index": "../Tracker.md"}})


def test_duplicate_keys_are_rejected():
    with pytest.raises(ConfigError, match="Duplicate"):
        config_mod.from_dict({"projects": [{"key": "a"}, {"key": "a"}]})


def test_an_unknown_default_project_is_caught_at_load():
    with pytest.raises(UnknownProject):
        config_mod.from_dict({"default_project": "nope", "projects": [{"key": "a"}]})


def test_unknown_project_lookup_lists_what_exists(cfg):
    with pytest.raises(UnknownProject, match="acme"):
        cfg.project("nope")


def test_inactive_projects_are_excluded_from_active_but_still_addressable(cfg):
    assert "retired" not in [p.key for p in cfg.active_projects()]
    assert cfg.project("retired").label == "Retired"


def test_tracker_path_defaults_to_the_project_folder(cfg):
    assert cfg.project("acme").tracker_path() == "acme/Tracker.md"


def test_invalid_output_flavor_is_rejected():
    with pytest.raises(ConfigError, match="flavor"):
        config_mod.from_dict({"output": {"flavor": "fancy"}})


# ------------------------------------------------- recording check-in


def test_check_in_defaults_to_an_hour_with_a_minute_to_answer():
    cfg = config_mod.from_dict({"notes_dir": "/tmp/notes"})
    assert cfg.capture.check_in_after == 3600
    assert cfg.capture.check_in_grace == 60


def test_check_in_settings_round_trip(tmp_path):
    cfg = config_mod.starter(notes_dir=tmp_path / "notes")
    tuned = config_mod.replace(
        cfg, capture=config_mod.replace(cfg.capture, check_in_after=1800, check_in_grace=15)
    )
    reloaded = config_mod.load(tuned.save(tmp_path / "config.toml"))
    assert reloaded.capture.check_in_after == 1800
    assert reloaded.capture.check_in_grace == 15


def test_zero_turns_the_check_in_off_without_complaint():
    cfg = config_mod.from_dict({"notes_dir": "/tmp/notes", "capture": {"check_in_after": 0}})
    assert cfg.capture.check_in_after == 0


@pytest.mark.parametrize("value", [-1, -3600])
def test_a_negative_interval_is_refused_rather_than_clamped(value):
    with pytest.raises(ConfigError, match="cannot be negative"):
        config_mod.from_dict({"notes_dir": "/tmp/notes", "capture": {"check_in_after": value}})


@pytest.mark.parametrize("value", ["3600", 60.5, True])
def test_a_non_integer_interval_names_the_setting(value):
    with pytest.raises(ConfigError, match="capture.check_in_grace"):
        config_mod.from_dict({"notes_dir": "/tmp/notes", "capture": {"check_in_grace": value}})
