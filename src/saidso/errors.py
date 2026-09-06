"""Exception types. Everything raised deliberately by saidso derives from SaidsoError.

The CLI catches SaidsoError and prints `message` without a traceback, so these
messages are user-facing copy: say what happened and what to do about it.
"""

from __future__ import annotations


class SaidsoError(Exception):
    """Base class for expected, actionable failures."""


class ConfigError(SaidsoError):
    """The config file is missing, malformed, or internally inconsistent."""


class UnknownProject(SaidsoError):
    """A project key was referenced that isn't in the config.

    Deliberately fatal rather than falling back to the default project: a typo
    in a filename token should stop the run and ask, not silently file a
    meeting under the wrong client.
    """


class MissingDependency(SaidsoError):
    """An optional extra is needed for this operation and isn't installed."""

    def __init__(self, package: str, extra: str, purpose: str) -> None:
        super().__init__(
            f"{purpose} needs {package}, which isn't installed.\n"
            f"Install it with:  pip install 'saidso[{extra}]'"
        )
        self.package = package
        self.extra = extra


class CaptureUnavailable(SaidsoError):
    """Live capture isn't supported on this platform, or no backend is usable."""


class ParseError(SaidsoError):
    """A transcript could not be parsed into utterances."""


class SyncError(SaidsoError):
    """A sync operation failed, or was refused because it looked unsafe."""
