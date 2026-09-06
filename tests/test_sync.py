"""The sync guard exists because an unattended script silently deleted a note.
These tests pin the two rules that prevent it recurring.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace

import pytest

from saidso.config import SyncSettings
from saidso.errors import SyncError
from saidso.sync import is_repo, sync

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _git_init(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


@pytest.fixture
def repo(cfg):
    root = cfg.notes_dir
    (root / "acme").mkdir(parents=True)
    _git_init(root)
    (root / "acme" / "note.md").write_text("a note\n", encoding="utf-8")
    (root / "acme" / "other.md").write_text("another\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return cfg


def test_a_non_repository_is_reported_clearly(cfg):
    cfg.notes_dir.mkdir(parents=True)
    with pytest.raises(SyncError, match="isn't a git repository"):
        sync(cfg)


def test_is_repo_detects_both_ways(cfg, tmp_path):
    assert not is_repo(tmp_path / "nowhere")


def test_a_new_note_is_committed(repo):
    (repo.notes_dir / "acme" / "new.md").write_text("new\n", encoding="utf-8")
    result = sync(repo, push=False)
    assert result.committed
    assert any("new.md" in s for s in result.staged)


def test_nothing_to_do_is_not_an_error(repo):
    result = sync(repo, push=False)
    assert not result.committed
    assert "nothing to commit" in result.log


def test_a_deletion_is_refused_by_default(repo):
    """The exact failure that lost a note: a file gone from one clone's tree."""
    (repo.notes_dir / "acme" / "note.md").unlink()
    result = sync(repo, push=False)
    assert not result.ok
    assert not result.committed
    assert "note.md" in result.refused
    # and nothing was left staged
    staged = subprocess.run(["git", "-C", str(repo.notes_dir), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout
    assert staged.strip() == ""


def test_a_deletion_is_committed_when_explicitly_allowed(repo):
    allowed = replace(repo, sync=SyncSettings(allow_deletions=True))
    (allowed.notes_dir / "acme" / "note.md").unlink()
    result = sync(allowed, push=False)
    assert result.committed
    assert result.deletions == ["acme/note.md"]


def test_dry_run_commits_nothing(repo):
    (repo.notes_dir / "acme" / "new.md").write_text("new\n", encoding="utf-8")
    result = sync(repo, push=False, dry_run=True)
    assert not result.committed
    head = subprocess.run(["git", "-C", str(repo.notes_dir), "log", "--oneline"],
                          capture_output=True, text=True).stdout
    assert head.count("\n") == 1
