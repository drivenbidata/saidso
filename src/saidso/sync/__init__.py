"""Optional mirroring of the notes directory. Off unless configured on."""

from __future__ import annotations

from .git import SyncResult, has_remote, is_repo, sync

__all__ = ["SyncResult", "has_remote", "is_repo", "sync"]
