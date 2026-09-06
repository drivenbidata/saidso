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


def test_a_folder_may_not_escape_the_notes_directory():
    with pytest.raises(ConfigError, match="may not escape"):
        config_mod.from_dict({"projects": [{"key": "esc", "folder": "../elsewhere"}]})


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
