"""The config is a file people edit by hand, so the message it fails with is
part of the product. These pin the shape of that message.
"""
from __future__ import annotations

import pytest

from saidso import config as config_mod
from saidso.errors import ConfigError

DUPLICATE_KEY = '''notes_dir = "C:/x"

[[projects]]
key = "general"
folder = "general"
active = true

key = "360"
label = "360"
'''


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_a_broken_config_names_the_file_the_line_and_the_cause(tmp_path):
    with pytest.raises(ConfigError) as caught:
        config_mod.load(_write(tmp_path, DUPLICATE_KEY))
    message = str(caught.value)
    assert "config.toml is not valid TOML" in message
    assert 'key = "360"' in message, "the offending line should be quoted back"
    assert "^" in message, "and pointed at"


def test_a_duplicate_key_suggests_the_missing_projects_header(tmp_path):
    """The mistake this config invites: pasting a second project's fields
    without giving it its own table header."""
    with pytest.raises(ConfigError) as caught:
        config_mod.load(_write(tmp_path, DUPLICATE_KEY))
    assert "[[projects]]" in str(caught.value)


def test_an_unrelated_syntax_error_does_not_get_the_projects_hint(tmp_path):
    with pytest.raises(ConfigError) as caught:
        config_mod.load(_write(tmp_path, 'notes_dir = "unclosed\n'))
    assert "[[projects]]" not in str(caught.value)


def test_a_valid_config_still_loads(tmp_path):
    cfg = config_mod.load(_write(tmp_path, DUPLICATE_KEY.replace('\nkey = "360"', '\n[[projects]]\nkey = "360"')))
    assert [p.key for p in cfg.projects] == ["general", "360"]
