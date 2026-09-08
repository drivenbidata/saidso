"""The pipeline: audio or a recording file in, a filed transcript out.

This is the layer the CLI and the desktop shell both drive, so that the two
never diverge in behaviour. Everything policy-shaped lives here; the modules
underneath stay mechanical.

The one piece of real cleverness is how speakers get labelled in a live
recording. Two tracks are captured — your microphone, and everything the
machine played — so your own speech is identified with certainty and no model.
Diarisation, when enabled, is applied only to the other track, to split it into
Speaker 1 / Speaker 2. That ordering is why saidso is useful with diarisation
switched off, which is the common case.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import dating, paths
from .capture import LOOPBACK, MIC, Recorder, Track, get_backend
from .config import Config
from .errors import SaidsoError
from .models import Segment, TranscriptMeta
from .output import naming, read_meta, routing, write_dialogue, write_transcript, write_vtt
from .parse import parse_file
from .transcribe import DiarizationResult, ProgressFn, WhisperTranscriber, diarize, is_media

OTHERS = "Others"


@dataclass(slots=True)
class Outcome:
    """What one transcription produced."""

    transcript: Path
    meta: TranscriptMeta
    route: routing.Route
    segments: int = 0
    vtt: Path | None = None
    diarization: DiarizationResult | None = None
    audio_kept: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    kind: str = "transcribed"  # or "ingested" - changes only how it is reported

    @property
    def project(self) -> str:
        return self.route.project.key


def _transcriber(cfg: Config, model: str | None = None) -> WhisperTranscriber:
    return WhisperTranscriber(model or cfg.transcribe.model)


def _write(
    cfg: Config,
    segments: list[Segment],
    meta: TranscriptMeta,
    route: routing.Route,
    *,
    vtt: bool | None = None,
) -> tuple[Path, Path | None]:
    basename = naming.build_basename(title=meta.title, when=meta.when, project=route.project.key)
    claimed = naming.claim(cfg.inbox_dir, basename, ".md")
    write_transcript(segments, claimed, meta)

    vtt_path = None
    if cfg.transcribe.vtt if vtt is None else vtt:
        vtt_path = claimed.with_suffix(".vtt")
        write_vtt(segments, vtt_path, meta)
    return claimed, vtt_path


def transcribe_file(
    cfg: Config,
    source: Path,
    *,
    project: str | None = None,
    title: str | None = None,
    when: dt.datetime | None = None,
    link: str = "",
    participants: list[str] | None = None,
    model: str | None = None,
    diarize_audio: bool | None = None,
    progress: ProgressFn | None = None,
) -> Outcome:
    """Transcribe one recording file and file the transcript in the inbox."""
    source = Path(source)
    if not source.exists():
        raise SaidsoError(f"No such recording: {source}")
    if not is_media(source):
        raise SaidsoError(
            f"{source.name} isn't a recognised audio or video file.\n"
            "If it is already a transcript (.vtt, .docx, .md, .txt), bring it in with:\n"
            f"  saidso ingest {source.name}"
        )

    route = routing.resolve(cfg, explicit=project, path=source)
    guess = dating.resolve(source, given=when)

    result = _transcriber(cfg, model).transcribe(
        source, language=cfg.transcribe.language or None, progress=progress
    )
    if not result.segments:
        raise SaidsoError(f"No speech detected in {source.name}.")

    diarization = None
    if diarize_audio if diarize_audio is not None else cfg.transcribe.diarize:
        if progress:
            progress(None, "Identifying speakers")
        diarization = diarize(source, result.segments)

    meta = TranscriptMeta(
        title=title or naming.title_from_path(source),
        when=guess.when,
        source=source.name,
        project=route.project.key,
        duration=result.duration,
        language=result.language,
        link=link,
        participants=list(participants or []),
        date_source=guess.source,
    )
    transcript, vtt_path = _write(cfg, result.segments, meta, route)

    outcome = Outcome(
        transcript=transcript,
        meta=meta,
        route=route,
        segments=len(result.segments),
        vtt=vtt_path,
        diarization=diarization,
    )
    if guess.inferred:
        outcome.notes.append(f"Date {guess.explanation}.")
    if route.note:
        outcome.notes.append(route.note)
    if diarization is not None and not diarization.applied:
        outcome.notes.append(f"Speaker labels skipped — {diarization.reason}.")
    return outcome


@dataclass(slots=True)
class MergedTracks:
    """The result of transcribing a mic track and a system track together."""

    segments: list[Segment] = field(default_factory=list)
    duration: float = 0.0
    language: str | None = None
    diarization: DiarizationResult | None = None


def merge_tracks(
    cfg: Config,
    tracks: list[tuple[str, Path]],
    *,
    model: str | None = None,
    diarize_audio: bool | None = None,
    progress: ProgressFn | None = None,
) -> MergedTracks:
    """Transcribe labelled tracks and interleave them into one conversation.

    `tracks` is a list of (label, path) where the label is "mic" or "system".
    The mic track is you — it is your microphone, so no model is needed to know
    that — and the system track is everyone else. Diarisation, when enabled, is
    applied only to the system track, to split "Others" into individuals.

    Shared by live recording and by transcribing a saved mic/system pair, so
    the two cannot drift: a pair of files off disk produces exactly the
    transcript the same meeting would have produced live.
    """
    me = cfg.speaker_name.strip() or "Me"
    transcriber = _transcriber(cfg, model)
    diarize_wanted = cfg.transcribe.diarize if diarize_audio is None else diarize_audio

    out = MergedTracks()
    for label, path in tracks:
        if progress:
            progress(None, f"Transcribing {label} track")
        result = transcriber.transcribe(
            path, language=cfg.transcribe.language or None, progress=progress
        )
        if not result.segments:
            continue
        if label == "system":
            if diarize_wanted:
                out.diarization = diarize(path, result.segments)
            for s in result.segments:
                if not s.speaker:
                    s.speaker = OTHERS
        else:
            for s in result.segments:
                s.speaker = me
        out.segments += result.segments
        out.duration = max(out.duration, result.duration or 0.0)
        out.language = out.language or result.language

    # Both tracks start at zero because they were recorded together, so sorting
    # by start time is what reassembles the conversation in order.
    out.segments.sort(key=lambda s: s.start)
    return out


# How a recorder names the two halves of one meeting. saidso writes `_mic` and
# `_system`; the others are here because real folders contain them.
MIC_MARKERS = ("_mic", "-mic")
SYSTEM_MARKERS = ("_system", "-system", "_speakers", "-speakers", "_sys")


def _track_role(stem: str) -> tuple[str, str] | None:
    """Split a filename stem into (shared base, role), or None if unpaired."""
    lowered = stem.lower()
    for marker in MIC_MARKERS:
        if lowered.endswith(marker):
            return stem[: -len(marker)], "mic"
    for marker in SYSTEM_MARKERS:
        if lowered.endswith(marker):
            return stem[: -len(marker)], "system"
    return None


def find_pairs(paths: list[Path]) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Group mic/system recordings of the same meeting.

    Returns (pairs as (mic, system), everything left over). Two files pair only
    when their names are identical apart from the role suffix — a `_mic` with no
    matching `_system` is just a recording, and is left alone rather than
    guessed at.
    """
    halves: dict[str, dict[str, Path]] = {}
    order: list[str] = []
    singles: list[Path] = []

    for path in paths:
        split = _track_role(path.stem)
        if split is None:
            singles.append(path)
            continue
        base, role = split
        key = f"{base.lower()}|{path.parent}"
        if key not in halves:
            halves[key] = {}
            order.append(key)
        # A second file in the same role is a different recording, not a pair.
        if role in halves[key]:
            singles.append(path)
        else:
            halves[key][role] = path

    pairs: list[tuple[Path, Path]] = []
    for key in order:
        found = halves[key]
        if "mic" in found and "system" in found:
            pairs.append((found["mic"], found["system"]))
        else:
            singles += list(found.values())
    return pairs, singles


def transcribe_pair(
    cfg: Config,
    mic: Path,
    system: Path,
    *,
    project: str | None = None,
    title: str | None = None,
    when: dt.datetime | None = None,
    link: str = "",
    participants: list[str] | None = None,
    model: str | None = None,
    diarize_audio: bool | None = None,
    progress: ProgressFn | None = None,
) -> Outcome:
    """Transcribe a saved mic/system pair as one meeting."""
    mic, system = Path(mic), Path(system)
    for path in (mic, system):
        if not path.exists():
            raise SaidsoError(f"No such recording: {path}")

    # Route and date from the shared part of the name, so the transcript is not
    # called "Meeting mic".
    base = mic.with_name(_track_role(mic.stem)[0].rstrip("_- ") + mic.suffix)
    route = routing.resolve(cfg, explicit=project, path=base)
    guess = dating.resolve(mic, given=when)

    merged = merge_tracks(
        cfg, [("mic", mic), ("system", system)],
        model=model, diarize_audio=diarize_audio, progress=progress,
    )
    if not merged.segments:
        raise SaidsoError(f"No speech detected in {mic.name} or {system.name}.")

    meta = TranscriptMeta(
        title=title or naming.title_from_path(base),
        when=guess.when,
        source=f"{mic.name} + {system.name}",
        project=route.project.key,
        duration=merged.duration,
        language=merged.language,
        link=link,
        participants=list(participants or []),
        date_source=guess.source,
    )
    transcript, vtt_path = _write(cfg, merged.segments, meta, route)

    outcome = Outcome(
        transcript=transcript,
        meta=meta,
        route=route,
        segments=len(merged.segments),
        vtt=vtt_path,
        diarization=merged.diarization,
        kind="paired",
    )
    outcome.notes.append(
        f"Combined two tracks: you from {mic.name}, everyone else from {system.name}."
    )
    if guess.inferred:
        outcome.notes.append(f"Date {guess.explanation}.")
    if route.note:
        outcome.notes.append(route.note)
    if merged.diarization is not None and not merged.diarization.applied:
        outcome.notes.append(
            f"Other participants are labelled '{OTHERS}' — {merged.diarization.reason}."
        )
    return outcome


def ingest_file(
    cfg: Config,
    source: Path,
    *,
    project: str | None = None,
    title: str | None = None,
    when: dt.datetime | None = None,
    link: str = "",
    participants: list[str] | None = None,
) -> Outcome:
    """Bring an existing transcript into the inbox, normalised and routed.

    The third way material arrives, after live recording and a media file: a
    transcript someone else's tool already produced — the .vtt or .docx a
    meeting platform hands you. Those need no transcription, but they do need
    everything else, and without this they have no way in at all.

    The dialogue is rewritten in saidso's own shape with proper frontmatter, so
    a transcript that came from an export is indistinguishable downstream from
    one saidso recorded. The original file is left exactly where it is —
    ingesting someone's file is not a reason to move it.
    """
    source = Path(source)
    if not source.exists():
        raise SaidsoError(f"No such transcript: {source}")

    result = parse_file(source)

    # A transcript's own frontmatter can name its project; the filename is the
    # fallback. Both run through the same routing as everything else.
    meta_block = read_meta(source) if source.suffix.lower() in (".md", ".markdown", ".txt") else {}
    route = routing.resolve(cfg, explicit=project, path=source, meta=meta_block)
    guess = dating.resolve(source, given=when)

    declared = str(meta_block.get("title") or "").strip()
    meta = TranscriptMeta(
        title=title or declared or naming.title_from_path(source),
        when=guess.when,
        source=source.name,
        project=route.project.key,
        link=link,
        participants=list(participants or []),
        date_source=guess.source,
    )

    basename = naming.build_basename(title=meta.title, when=meta.when, project=route.project.key)
    claimed = naming.claim(cfg.inbox_dir, basename, ".md")
    write_dialogue(result.utterances, claimed, meta)

    outcome = Outcome(
        transcript=claimed,
        meta=meta,
        route=route,
        segments=len(result.utterances),
        kind="ingested",
    )
    if guess.inferred:
        outcome.notes.append(f"Date {guess.explanation}.")
    if route.note:
        outcome.notes.append(route.note)
    if not result.attributed:
        outcome.notes.append(
            "No speaker structure in the source, so nothing can be attributed — "
            "the dialogue is kept as one block."
        )
    return outcome


class LiveSession:
    """A meeting being recorded right now.

    Deliberately a small object rather than a blocking call: the desktop shell
    needs to start it, show a timer, and stop it from a different thread, and
    the CLI needs the same thing with a keypress.
    """

    def __init__(
        self,
        cfg: Config,
        *,
        title: str | None = None,
        project: str | None = None,
        link: str = "",
        participants: list[str] | None = None,
        model: str | None = None,
        diarize_audio: bool | None = None,
    ) -> None:
        self.cfg = cfg
        self.started_at = dt.datetime.now()
        self.title = title or f"Meeting {self.started_at:%H-%M}"
        self.route = routing.resolve(cfg, explicit=project or cfg.default_project)
        self.link = link
        self.participants = list(participants or [])
        self.model = model
        self.diarize_audio = cfg.transcribe.diarize if diarize_audio is None else diarize_audio

        self.backend = get_backend(cfg.capture.backend)
        self.mic = self.backend.resolve(cfg.capture.mic, MIC)
        self.system = self.backend.resolve(cfg.capture.system, LOOPBACK)

        basename = f"{self.started_at:%Y-%m-%d_%H%M}_{naming.slugify(self.title)}"
        self.recorder = Recorder(
            self.backend,
            mic=self.mic,
            system=self.system,
            dest_dir=paths.recordings_dir(),
            basename=basename,
        )

    @property
    def elapsed(self) -> float:
        return self.recorder.elapsed

    @property
    def running(self) -> bool:
        return self.recorder.running

    def start(self) -> None:
        self.recorder.start()

    def cancel(self) -> None:
        """Stop and discard, leaving nothing behind."""
        for track in self.recorder.stop():
            track.path.unlink(missing_ok=True)
        self.backend.close()

    def stop(self, *, progress: ProgressFn | None = None) -> Outcome:
        """Stop recording, transcribe both tracks, and file the transcript."""
        tracks = self.recorder.stop()
        self.backend.close()
        if not tracks:
            raise SaidsoError(
                "Nothing was recorded. Check that the microphone and system-audio "
                "devices are the right ones (`saidso devices`)."
            )

        merged = merge_tracks(
            self.cfg,
            [(track.label, track.path) for track in tracks],
            model=self.model,
            diarize_audio=self.diarize_audio,
            progress=progress,
        )
        if not merged.segments:
            raise SaidsoError("No speech detected in the recording.")

        meta = TranscriptMeta(
            title=self.title,
            when=self.started_at,
            source="live recording",
            project=self.route.project.key,
            duration=merged.duration,
            language=merged.language,
            link=self.link,
            participants=self.participants,
            date_source="recorded",
        )
        transcript, vtt_path = _write(self.cfg, merged.segments, meta, self.route)

        kept = self._handle_audio(tracks)
        outcome = Outcome(
            transcript=transcript,
            meta=meta,
            route=self.route,
            segments=len(merged.segments),
            vtt=vtt_path,
            diarization=merged.diarization,
            audio_kept=kept,
        )
        if merged.diarization is not None and not merged.diarization.applied:
            outcome.notes.append(
                f"Other participants are labelled '{OTHERS}' — {merged.diarization.reason}."
            )
        return outcome

    def _handle_audio(self, tracks: list[Track]) -> list[Path]:
        if not self.cfg.capture.keep_audio:
            for track in tracks:
                track.path.unlink(missing_ok=True)
            return []
        dest = self.cfg.recordings_dir
        dest.mkdir(parents=True, exist_ok=True)
        kept: list[Path] = []
        for track in tracks:
            target = dest / track.path.name
            shutil.move(str(track.path), target)
            kept.append(target)
        return kept
