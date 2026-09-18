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

import re
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
    `folder` is where notes land, relative to the notes directory — or an
    absolute path, for a project whose notes already live in a vault of their
    own and are not being moved.
    """

    key: str
    label: str
    folder: str
    tracker: str = ""
    description: str = ""
    active: bool = True

    @property
    def is_external(self) -> bool:
        """True when the notes live outside the notes directory.

        Worth checking before assuming a project's files are reachable from
        `notes_dir` — sync and the tracker index both are.
        """
        return Path(self.folder).is_absolute()

    def tracker_path(self) -> str:
        if self.tracker:
            return self.tracker
        if self.is_external:
            return str(Path(self.folder) / "Tracker.md")
        return f"{self.folder}/Tracker.md"


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
    # A recording nobody stopped is the most expensive kind of mistake here: it
    # keeps the microphone, fills the disk, and buries a real meeting inside
    # hours of whatever the room happened to play. So a long recording is asked
    # whether it is still a meeting, and stops itself when nothing answers.
    # Seconds between check-ins; 0 disables the watchdog entirely.
    check_in_after: int = 3600
    # Seconds to answer before the recording stops and transcribes itself.
    check_in_grace: int = 60


@dataclass(frozen=True, slots=True)
class OutputSettings:
    flavor: str = "plain"  # plain | obsidian
    inbox: str = "inbox"
    processed: str = "processed"
    recordings: str = "recordings"


@dataclass(frozen=True, slots=True)
class TrackerSettings:
    enabled: bool = True
    # Root index; holds counts only, never items. Relative to notes_dir, or an
    # absolute path — which is what an external project needs, so the index can
    # sit beside the notes it counts rather than beside the config.
    index: str = "Tracker.md"


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
        """Where this project's notes live.

        Joining an absolute folder discards `notes_dir`, which is exactly what
        an external project wants — see `Project.is_external`.
        """
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
                "check_in_after": self.capture.check_in_after,
                "check_in_grace": self.capture.check_in_grace,
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


def _checked_location(value: str, what: str) -> str:
    """A path that is either relative to notes_dir or frankly absolute.

    Absolute is allowed because notes sometimes already live somewhere and are
    not moving. `..` is not, in either form: a path that climbs is doing the
    same thing without saying so, and is silent about where it lands.
    """
    if ".." in Path(value).parts:
        raise ConfigError(
            f"{what} is {value!r}. A relative path may not escape notes_dir with "
            "'..'. If it genuinely lives elsewhere, give the absolute path instead — "
            "that is explicit and survives a move of notes_dir."
        )
    return value


def _seconds(raw: dict[str, Any], key: str, default: int) -> int:
    """A non-negative whole number of seconds, or a clear error.

    A negative interval would arm a watchdog that fires immediately and stops
    the recording it was meant to protect, so it is refused at load rather than
    clamped — someone who typed -1 meant something, and 0 already means off.
    """
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"capture.{key} must be a whole number of seconds, not {value!r}.")
    if value < 0:
        raise ConfigError(f"capture.{key} cannot be negative (0 turns it off).")
    return value


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
    folder = _checked_location(str(raw.get("folder") or key).strip(), f"Project {key!r} folder")
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
            check_in_after=_seconds(c, "check_in_after", 3600),
            check_in_grace=_seconds(c, "check_in_grace", 60),
        ),
        output=OutputSettings(
            flavor=flavor,
            inbox=str(o.get("inbox", "inbox")),
            processed=str(o.get("processed", "processed")),
            recordings=str(o.get("recordings", "recordings")),
        ),
        tracker=TrackerSettings(
            enabled=bool(tr.get("enabled", True)),
            index=_checked_location(str(tr.get("index", "Tracker.md")), "The tracker index"),
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
        text = target.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Could not read {target}: {e}") from e
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(explain_toml_error(target, text, e)) from e
    return from_dict(data, source=target)


def explain_toml_error(target: Path, text: str, error: Exception) -> str:
    """Turn a parser message into something a person can act on.

    tomllib reports "Cannot overwrite a value (at line 45, column 12)", which is
    accurate and nearly useless: it names neither the file nor the line's
    contents, and says nothing about the cause. Since the config is a file we
    ask people to edit by hand, the message it fails with is part of the
    product.
    """
    message = str(error)
    lines = [f"{target} is not valid TOML.", ""]

    match = re.search(r"\(at line (\d+), column (\d+)\)", message)
    if match:
        number, column = int(match.group(1)), int(match.group(2))
        source = text.splitlines()
        if 1 <= number <= len(source):
            lines.append(f"  {number:>4} | {source[number - 1]}")
            lines.append(f"       | {' ' * max(column - 1, 0)}^")
            lines.append("")
    lines.append(f"  {message}")

    # The mistake this config invites, by a wide margin: pasting a second
    # project's fields without giving it its own table header, so the keys land
    # in the previous project and collide.
    if "overwrite" in message.lower() or "duplicate" in message.lower():
        lines += [
            "",
            "A duplicated key usually means a `[[projects]]` header is missing.",
            "Every project needs its own, and the double brackets are what make",
            "it a list:",
            "",
            "    [[projects]]",
            '    key = "general"',
            "    ...",
            "",
            "    [[projects]]      <- this line is easy to leave out",
            '    key = "360"',
        ]
    return "\n".join(lines)
