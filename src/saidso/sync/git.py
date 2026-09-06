"""Optional git mirroring of the notes directory.

This exists because the pipeline saidso grew out of lost a meeting note to an
unattended sync, and the fix belongs in code rather than in a runbook nobody
reads at 22:30. The sequence that lost it was:

    git add -A          # the working tree becomes truth
    git pull --rebase   # reconciliation, too late
    git push

Staging first means any file present in HEAD but absent from *this* working
tree is committed as a deletion — so a machine that never had the note deletes
it for everyone. Two rules follow, and both are enforced here rather than
documented:

1. **Pull before staging.** Always. This alone prevents the whole class.
2. **Never commit a deletion you didn't make.** An unattended sync should
   essentially never delete anything, so a staged deletion aborts the commit
   and is reported loudly. `sync.allow_deletions = true` opts out, for people
   who genuinely delete notes and want them mirrored.

Credentials are deliberately not managed here. Whatever git already uses for
the repository is what saidso uses — no tokens written to disk by this tool.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..errors import SyncError

TIMEOUT = 120


@dataclass(slots=True)
class SyncResult:
    committed: bool = False
    pushed: bool = False
    staged: list[str] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    message: str = ""
    log: list[str] = field(default_factory=list)
    refused: str = ""

    @property
    def ok(self) -> bool:
        return not self.refused


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise SyncError(
            f"git {' '.join(args)} failed ({proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc


def is_repo(path: Path) -> bool:
    try:
        proc = _run(Path(path), "rev-parse", "--is-inside-work-tree", check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def has_remote(repo: Path, name: str) -> bool:
    proc = _run(Path(repo), "remote", check=False)
    return name in proc.stdout.split()


def sync(
    cfg: Config,
    *,
    message: str | None = None,
    push: bool = True,
    paths: list[str] | None = None,
    dry_run: bool = False,
) -> SyncResult:
    """Pull, stage, guard, commit, push. Returns what happened."""
    repo = cfg.notes_dir
    result = SyncResult()

    if not is_repo(repo):
        raise SyncError(
            f"{repo} isn't a git repository.\n"
            "Run `git init` there and add a remote, or turn sync off with "
            "sync.enabled = false."
        )

    # 1. Pull first, always — before anything is staged.
    if has_remote(repo, cfg.sync.remote):
        proc = _run(repo, "pull", "--rebase", "--autostash", cfg.sync.remote, cfg.sync.branch, check=False)
        if proc.returncode != 0:
            raise SyncError(
                "Pull failed, so nothing was staged or committed — the working tree "
                f"is untouched:\n{(proc.stderr or proc.stdout).strip()}"
            )
        result.log.append(f"pulled {cfg.sync.remote}/{cfg.sync.branch}")
    else:
        result.log.append(f"no remote named {cfg.sync.remote!r}; working locally")

    # 2. Stage. Scoped to what saidso actually writes, so the sync can't express
    #    an opinion about files it doesn't own.
    targets = paths if paths is not None else _owned_paths(cfg)
    if targets:
        _run(repo, "add", "--", *targets, check=False)
    else:
        _run(repo, "add", "-A")

    staged = _run(repo, "diff", "--cached", "--name-only").stdout.split("\n")
    result.staged = [s for s in (x.strip() for x in staged) if s]
    if not result.staged:
        result.log.append("nothing to commit")
        return result

    # 3. Guard: refuse to commit deletions this run didn't intend.
    deleted = _run(repo, "diff", "--cached", "--diff-filter=D", "--name-only").stdout.split("\n")
    result.deletions = [s for s in (x.strip() for x in deleted) if s]
    if result.deletions and not cfg.sync.allow_deletions:
        _run(repo, "reset", check=False)  # unstage; leave the working tree alone
        result.refused = (
            f"Refusing to commit {len(result.deletions)} deletion(s):\n  "
            + "\n  ".join(result.deletions[:10])
            + "\n\nAn unattended sync should not delete notes. If another machine "
            "created these, pull there instead. If you really did delete them, set "
            "sync.allow_deletions = true or commit them by hand."
        )
        return result

    result.message = message or f"saidso sync {dt.datetime.now():%Y-%m-%d %H:%M}"
    if dry_run:
        _run(repo, "reset", check=False)
        result.log.append(f"dry run: would commit {len(result.staged)} path(s)")
        return result

    _run(repo, "commit", "-m", result.message)
    result.committed = True
    result.log.append(f"committed {len(result.staged)} path(s)")
    if result.deletions:
        # Explicitly, because "Committed changes: <names>" hid a deletion once.
        result.log.append(f"including {len(result.deletions)} deletion(s): {', '.join(result.deletions[:5])}")

    if push and has_remote(repo, cfg.sync.remote):
        proc = _run(repo, "push", cfg.sync.remote, f"HEAD:{cfg.sync.branch}", check=False)
        if proc.returncode != 0:
            raise SyncError(
                "Commit succeeded but push failed, so the change is safe locally:\n"
                f"{(proc.stderr or proc.stdout).strip()}"
            )
        result.pushed = True
        result.log.append(f"pushed to {cfg.sync.remote}/{cfg.sync.branch}")

    return result


def _owned_paths(cfg: Config) -> list[str]:
    """The paths saidso writes, relative to the notes directory."""
    owned = [cfg.output.inbox, cfg.output.processed, cfg.tracker.index]
    owned += [p.folder for p in cfg.projects]
    seen: list[str] = []
    for path in owned:
        rel = str(path).strip().strip("/")
        if rel and rel not in seen and (cfg.notes_dir / rel).exists():
            seen.append(rel)
    return seen
