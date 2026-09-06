"""Turning transcription results into files on disk, filed by project."""

from __future__ import annotations

from . import frontmatter, naming, routing
from .markdown import (
    build_frontmatter,
    read_meta,
    render_transcript,
    render_vtt,
    speakers_of,
    write_atomic,
    write_transcript,
    write_vtt,
)
from .naming import build_basename, claim, slugify
from .routing import Route
from .routing import resolve as resolve_project

__all__ = [
    "Route",
    "build_basename",
    "build_frontmatter",
    "claim",
    "frontmatter",
    "naming",
    "read_meta",
    "render_transcript",
    "render_vtt",
    "resolve_project",
    "routing",
    "slugify",
    "speakers_of",
    "write_atomic",
    "write_transcript",
    "write_vtt",
]
