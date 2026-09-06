"""User configuration — a single TOML file, read by every part of saidso.

The design rule inherited from the prototype: the project list is data, never
code. Adding or retiring a project is a config edit and nothing else, and every
component reads the same file so the CLI, the desktop shell and the agent pack
can't drift apart.

The one behaviour worth calling out is `Config.project()`: an unknown key is a
hard error, not a fall back to the default. A typo in a filename token should
stop the run and ask rather than quietly filing a meeting under the wrong
client — recovering from that later means finding it first.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import tomli_w

from . import paths
from .errors import ConfigError, UnknownProject

CONFIG_VERSION = 1

_FORBIDDEN_IN_KEY = set(' \t/\\:*?"<>|')


@dataclass(frozen=True, slots=True)
class Project:
    """One destination for meeting notes.

    `key` is the token that appears in transcript filenames and frontmatter;
    `folder` is where notes land, relative to the notes directory.
    """

    key: str
    label: str
    folder: str
    tracker: str = ""
    description: str = ""
    active: bool = True

    def tracker_path(self) -> str:
        return self.tracker or f"{self.folder}/Tracker.md"


@dataclass(frozen=True, slots=True)
class TranscribeSettings:
    model: str = "base"
    language: str = ""  # "" means auto-detect
    diarize: bool = False
    vtt: bool = False


@dataclass(frozen=True, slots=True)
class CaptureSettings:
    backend: str = "auto"  # auto | wasapi | none
    mic: str = ""  # device index or name fragment; "" = system default
    system: str = ""  # loopback device; "" = system default output
    keep_audio: bool = False


@dataclass(frozen=True, slots=True)
class OutputSettings:
    flavor: str = "plain"  # plain | obsidian
    inbox: str = "inbox"
    processed: str = "processed"
    recordings: str = "recordings"


@dataclass(frozen=True, slots=True)
class TrackerSettings:
    enabled: bool = True
    index: str = "Tracker.md"  # root index; holds counts only, never items


@dataclass(frozen=True, slots=True)
class SyncSettings:
    enabled: bool = False
    mode: str = "git"
    remote: str = "origin"
    branch: str = "main"
    allow_deletions: bool = False  # load-bearing default; see sync/git.py


@dataclass(frozen=True, slots=True)
class Config:
    notes_dir: Path
    speaker_name: str = ""
    default_project: str = "general"
    projects: tuple[Project, ...] = ()
    transcribe: TranscribeSettings = field(default_factory=TranscribeSettings)
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    tracker: TrackerSettings = field(default_factory=TrackerSettings)
    sync: SyncSettings = field(default_factory=SyncSettings)
    source_path: Path | None = None

    # ------------------------------------------------------------ resolution

    @property
    def inbox_dir(self) -> Path:
        return self.notes_dir / self.output.inbox

    @property
    def processed_dir(self) -> Path:
        return self.notes_dir / self.output.processed

    @property
    def recordings_dir(self) -> Path:
        return self.notes_dir / self.output.recordings

    @property
    def index_path(self) -> Path:
        return self.notes_dir / self.tracker.index

    def active_projects(self) -> list[Project]:
        return [p for p in self.projects if p.active]

    def project(self, key: str | None = None) -> Project:
        """Look up a project by key. Unknown keys raise rather than defaulting."""
        wanted = (key or self.default_project or "").strip()
        if not wanted:
            raise UnknownProject("No project given and no default_project is configured.")
        for p in self.projects:
            if p.key == wanted:
                return p
        known = ", ".join(p.key for p in self.projects) or "(none configured)"
        raise UnknownProject(
            f"Unknown project {wanted!r}. Configured projects: {known}.\n"
            f"Add it to {self.source_path or paths.config_file()} or use one of the above."
        )

    def project_dir(self, key: str | None = None) -> Path:
        return self.notes_dir / self.project(key).folder

    def tracker_path(self, key: str | None = None) -> Path:
        return self.notes_dir / self.project(key).tracker_path()

    def with_overrides(self, **kw: Any) -> Config:
        """Return a copy with top-level fields replaced (used by CLI flags)."""
        return replace(self, **{k: v for k, v in kw.items() if v is not None})

    # ------------------------------------------------------------ (de)serialise

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "notes_dir": str(self.notes_dir),
            "default_project": self.default_project,
            "identity": {"name": self.speaker_name},
            "transcribe": {
                "model": self.transcribe.model,
                "language": self.transcribe.language,
                "diarize": self.transcribe.diarize,
                "vtt": self.transcribe.vtt,
            },
            "capture": {
                "backend": self.capture.backend,
                "mic": self.capture.mic,
                "system": self.capture.system,
                "keep_audio": self.capture.keep_audio,
            },
            "output": {
                "flavor": self.output.flavor,
                "inbox": self.output.inbox,
                "processed": self.output.processed,
                "recordings": self.output.recordings,
            },
            "tracker": {"enabled": self.tracker.enabled, "index": self.tracker.index},
            "sync": {
                "enabled": self.sync.enabled,
                "mode": self.sync.mode,
                "remote": self.sync.remote,
                "branch": self.sync.branch,
                "allow_deletions": self.sync.allow_deletions,
            },
            "projects": [
                {
                    "key": p.key,
                    "label": p.label,
                    "folder": p.folder,
                    "tracker": p.tracker_path(),
                    "description": p.description,
                    "active": p.active,
                }
                for p in self.projects
            ],
        }

    def save(self, path: Path | None = None) -> Path:
        target = path or self.source_path or paths.config_file()
        paths.ensure(target.parent)
        target.write_text(tomli_w.dumps(self.to_dict()), encoding="utf-8")
        return target


def _project_from(raw: dict[str, Any], index: int) -> Project:
    key = str(raw.get("key", "")).strip()
    if not key:
        raise ConfigError(f"projects[{index}] has no 'key'.")
    if bad := _FORBIDDEN_IN_KEY & set(key):
        raise ConfigError(
            f"Project key {key!r} contains {''.join(sorted(bad))!r}. "
            "Keys go into filenames and frontmatter, so they must have no spaces "
            "or path separators."
        )
    folder = str(raw.get("folder") or key).strip()
    if Path(folder).is_absolute() or ".." in Path(folder).parts:
        raise ConfigError(
            f"Project {key!r} has folder {folder!r}. Folders are relative to notes_dir "
            "and may not escape it."
        )
    return Project(
        key=key,
        label=str(raw.get("label") or key),
        folder=folder,
        tracker=str(raw.get("tracker") or ""),
        description=str(raw.get("description") or ""),
        active=bool(raw.get("active", True)),
    )


def from_dict(data: dict[str, Any], source: Path | None = None) -> Config:
    version = int(data.get("version", CONFIG_VERSION))
    if version > CONFIG_VERSION:
        raise ConfigError(
            f"Config at {source} is version {version}, but this saidso understands "
            f"up to {CONFIG_VERSION}. Upgrade saidso."
        )

    notes_raw = str(data.get("notes_dir") or "").strip()
    notes_dir = Path(notes_raw).expanduser() if notes_raw else paths.default_notes_dir()

    projects = tuple(
        _project_from(p, i) for i, p in enumerate(data.get("projects") or [])
    )
    seen: set[str] = set()
    for p in projects:
        if p.key in seen:
            raise ConfigError(f"Duplicate project key {p.key!r}.")
        seen.add(p.key)

    t = data.get("transcribe") or {}
    c = data.get("capture") or {}
    o = data.get("output") or {}
    tr = data.get("tracker") or {}
    s = data.get("sync") or {}

    flavor = str(o.get("flavor", "plain"))
    if flavor not in ("plain", "obsidian"):
        raise ConfigError(f"output.flavor must be 'plain' or 'obsidian', not {flavor!r}.")

    cfg = Config(
        notes_dir=notes_dir,
        speaker_name=str((data.get("identity") or {}).get("name") or ""),
        default_project=str(data.get("default_project") or (projects[0].key if projects else "")),
        projects=projects,
        transcribe=TranscribeSettings(
            model=str(t.get("model", "base")),
            language=str(t.get("language", "")),
            diarize=bool(t.get("diarize", False)),
            vtt=bool(t.get("vtt", False)),
        ),
        capture=CaptureSettings(
            backend=str(c.get("backend", "auto")),
            mic=str(c.get("mic", "")),
            system=str(c.get("system", "")),
            keep_audio=bool(c.get("keep_audio", False)),
        ),
        output=OutputSettings(
            flavor=flavor,
            inbox=str(o.get("inbox", "inbox")),
            processed=str(o.get("processed", "processed")),
            recordings=str(o.get("recordings", "recordings")),
        ),
        tracker=TrackerSettings(
            enabled=bool(tr.get("enabled", True)),
            index=str(tr.get("index", "Tracker.md")),
        ),
        sync=SyncSettings(
            enabled=bool(s.get("enabled", False)),
            mode=str(s.get("mode", "git")),
            remote=str(s.get("remote", "origin")),
            branch=str(s.get("branch", "main")),
            allow_deletions=bool(s.get("allow_deletions", False)),
        ),
        source_path=source,
    )

    if cfg.projects and cfg.default_project:
        cfg.project(cfg.default_project)  # raises UnknownProject if it doesn't exist
    return cfg


def starter(notes_dir: Path | None = None, speaker_name: str = "") -> Config:
    """The config a first run writes: one project, nothing clever."""
    return Config(
        notes_dir=notes_dir or paths.default_notes_dir(),
        speaker_name=speaker_name,
        default_project="general",
        projects=(
            Project(
                key="general",
                label="General",
                folder="general",
                description="Default destination for meetings that aren't routed elsewhere.",
            ),
        ),
    )


def load(path: Path | None = None, *, create: bool = False) -> Config:
    """Load the config. With create=True, write and return a starter if absent."""
    target = path or paths.config_file()
    if not target.exists():
        if not create:
            raise ConfigError(
                f"No config at {target}.\nRun:  saidso init"
            )
        cfg = starter()
        cfg.save(target)
        return replace(cfg, source_path=target)
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{target} is not valid TOML: {e}") from e
    except OSError as e:
        raise ConfigError(f"Could not read {target}: {e}") from e
    return from_dict(data, source=target)
