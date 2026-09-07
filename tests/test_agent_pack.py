"""A Claude skill is installed by copying one directory, so everything it
references has to live inside that directory.

This is pinned because it failed in practice: the prompt and template sat
beside the skill rather than inside it, `cp -r` produced a skill whose own
instructions pointed at missing files, and nothing noticed until an agent
tried to follow them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1] / "agent-pack" / "skills" / "saidso-meeting-notes"


def test_the_skill_exists_with_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "a skill needs YAML frontmatter"
    assert re.search(r"^name:\s*\"?saidso-meeting-notes", text, re.M)
    assert re.search(r"^description:", text, re.M)


def test_every_file_the_skill_references_is_inside_the_skill():
    """The bug: `templates/output-template.md` resolved to nothing once installed."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    referenced = set(re.findall(r"`((?:templates|prompts|scripts)/[\w.-]+)`", text))
    assert referenced, "expected the skill to reference its own supporting files"
    missing = sorted(r for r in referenced if not (SKILL_DIR / r).exists())
    assert not missing, f"referenced but not shipped with the skill: {missing}"


@pytest.mark.parametrize("relative", ["prompts/meeting-notes.md", "templates/output-template.md"])
def test_the_supporting_files_have_content(relative):
    assert len((SKILL_DIR / relative).read_text(encoding="utf-8").strip()) > 500


def test_the_skill_drives_the_cli_rather_than_editing_files_directly():
    """The tracker format and the sweep depend on `saidso tracker add`."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "saidso tracker add" in text
    assert "saidso parse" in text
    assert "Never write to `## Completed`" in text


def test_no_personal_identifiers_leaked_into_the_pack():
    """The pack came from one person's private pipeline; it ships to everyone."""
    banned = ("Middl8", "Omnissa", "Qlik", "jford", "360insights")
    for path in SKILL_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        found = [b for b in banned if b in text]
        assert not found, f"{path.name} still mentions {found}"
