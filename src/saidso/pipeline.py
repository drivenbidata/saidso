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

        me = self.cfg.speaker_name.strip() or "Me"
        transcriber = _transcriber(self.cfg, self.model)
        segments: list[Segment] = []
        duration = 0.0
        language: str | None = None
        diarization: DiarizationResult | None = None

        for track in tracks:
            if progress:
                progress(None, f"Transcribing {track.label} track")
            result = transcriber.transcribe(
                track.path, language=self.cfg.transcribe.language or None, progress=progress
            )
            if not result.segments:
                continue
            if track.label == "system":
                # Only the other participants need splitting apart.
                if self.diarize_audio:
                    diarization = diarize(track.path, result.segments)
                for s in result.segments:
                    if not s.speaker:
                        s.speaker = OTHERS
            else:
                for s in result.segments:
                    s.speaker = me
            segments += result.segments
            duration = max(duration, result.duration or 0.0)
            language = language or result.language

        if not segments:
            raise SaidsoError("No speech detected in the recording.")
        segments.sort(key=lambda s: s.start)

        meta = TranscriptMeta(
            title=self.title,
            when=self.started_at,
            source="live recording",
            project=self.route.project.key,
            duration=duration,
            language=language,
            link=self.link,
            participants=self.participants,
            date_source="recorded",
        )
        transcript, vtt_path = _write(self.cfg, segments, meta, self.route)

        kept = self._handle_audio(tracks)
        outcome = Outcome(
            transcript=transcript,
            meta=meta,
            route=self.route,
            segments=len(segments),
            vtt=vtt_path,
            diarization=diarization,
            audio_kept=kept,
        )
        if diarization is not None and not diarization.applied:
            outcome.notes.append(
                f"Other participants are labelled '{OTHERS}' — {diarization.reason}."
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
