"""A small localhost API, so the desktop shell drives the same code the CLI does.

Deliberately built on the standard library. The engine is already the heavy
part of any bundle — a web framework on top of it would be weight for a server
that binds to 127.0.0.1, serves one client, and exists only because Electron
can't call Python functions directly.

Three properties matter:

* **Loopback only, with a token.** The port is bound to 127.0.0.1 and every
  request must carry the token printed on startup. Anything else on the machine
  can reach a loopback port, and this API records audio.
* **Port 0 by default.** The parent process reads the real port from the
  handshake line on stdout, so two instances never fight over a fixed port.
* **Progress is streamed.** Transcription takes minutes; `GET /events` is a
  Server-Sent Events stream, which is enough for one-way progress and needs no
  dependency.

Run it directly to see it work:

    python -m saidso.server --port 8420 --token dev
"""

from __future__ import annotations

import argparse
import contextlib
import json
import queue
import secrets
import sys
import threading
import traceback
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from . import config as config_mod
from .errors import SaidsoError

HANDSHAKE = "saidso-server"


class Events:
    """Fan-out of progress events to every connected listener."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=512)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, kind: str, **data: Any) -> None:
        payload = {"type": kind, **data}
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            # A listener that can't keep up loses events, not the job.
            with contextlib.suppress(queue.Full):
                q.put_nowait(payload)


class Engine:
    """Everything the shell can ask for, holding the one live session."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self.events = Events()
        self.session = None  # LiveSession | None
        self.busy = False
        self._lock = threading.Lock()

    def config(self):
        """The current config, created with defaults if there isn't one yet.

        The CLI tells you to run `saidso init`; a window cannot. Someone who
        installs the desktop app and has never opened a terminal must get a
        working app on first launch, not an error they have no way to act on.
        The config is written to disk so it is then editable and visible, and
        the window shows which notes directory it chose.
        """
        return config_mod.load(self.config_path, create=True)

    # ------------------------------------------------------------ progress

    def _progress(self):
        def report(fraction: float | None, message: str) -> None:
            self.events.emit("progress", fraction=fraction, message=message)

        return report

    def _run(self, name: str, fn) -> None:
        """Run work on a thread, reporting the outcome as events."""

        def worker() -> None:
            try:
                result = fn()
                self.events.emit("done", job=name, result=result)
            except SaidsoError as e:
                self.events.emit("error", job=name, message=str(e))
            except Exception as e:  # noqa: BLE001 - surfaced to the UI, not swallowed
                self.events.emit(
                    "error", job=name, message=f"{type(e).__name__}: {e}",
                    detail=traceback.format_exc(),
                )
            finally:
                self.busy = False
                self.events.emit("idle")

        with self._lock:
            if self.busy:
                raise SaidsoError("Already busy — wait for the current job to finish.")
            self.busy = True
        threading.Thread(target=worker, daemon=True, name=f"saidso-{name}").start()

    # ------------------------------------------------------------ actions

    def devices(self) -> dict[str, Any]:
        from .capture import LOOPBACK, MIC, get_backend
        from .errors import CaptureUnavailable

        cfg = self.config()
        try:
            backend = get_backend(cfg.capture.backend)
        except CaptureUnavailable as e:
            return {"available": False, "reason": str(e), "mics": [], "system": []}
        try:
            found = backend.devices()
            return {
                "available": True,
                "backend": backend.id,
                "mics": [asdict(d) for d in found if d.kind == MIC],
                "system": [asdict(d) for d in found if d.kind == LOOPBACK],
            }
        finally:
            backend.close()

    def projects(self) -> dict[str, Any]:
        cfg = self.config()
        # tracker is resolved rather than passed through: the stored field is
        # empty when it defaults, and a caller reading this shouldn't have to
        # know the defaulting rule.
        return {
            "default": cfg.default_project,
            "projects": [
                {**asdict(p), "tracker": p.tracker_path()} for p in cfg.active_projects()
            ],
        }

    def settings(self) -> dict[str, Any]:
        cfg = self.config()
        return {
            "version": __version__,
            "config_path": str(cfg.source_path or ""),
            "notes_dir": str(cfg.notes_dir),
            "inbox": str(cfg.inbox_dir),
            "speaker_name": cfg.speaker_name,
            "model": cfg.transcribe.model,
            "diarize": cfg.transcribe.diarize,
            "flavor": cfg.output.flavor,
        }

    def update_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        """Change the settings a person can reasonably edit from a window.

        Only these fields: everything else in the config is either structural
        (the project list) or better left to the file, and a settings endpoint
        that can rewrite anything is a settings endpoint that can corrupt
        anything. The result is written to the same config.toml the CLI reads,
        so the two views never diverge.
        """
        from dataclasses import replace

        cfg = self.config()
        changed: dict[str, Any] = {}

        if "notes_dir" in body:
            raw = str(body["notes_dir"] or "").strip()
            if not raw:
                raise SaidsoError("The notes folder can't be empty.")
            target = Path(raw).expanduser()
            if target.exists() and not target.is_dir():
                raise SaidsoError(f"{target} is a file, not a folder.")
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise SaidsoError(f"Can't use {target}: {e}") from e
            changed["notes_dir"] = target

        if "speaker_name" in body:
            # This becomes the speaker tag on your own microphone track, so it
            # ends up in every transcript's frontmatter.
            changed["speaker_name"] = str(body["speaker_name"] or "").strip()

        if "model" in body:
            from .transcribe import MODELS

            model = str(body["model"] or "").strip()
            if model not in MODELS:
                raise SaidsoError(f"Unknown model {model!r}. One of: {', '.join(MODELS)}")
            changed["transcribe"] = replace(cfg.transcribe, model=model)

        if not changed:
            return self.settings()

        replace(cfg, **changed).save()
        self.events.emit("settings", **{k: str(v) for k, v in changed.items()})
        return self.settings()

    def inbox(self, limit: int = 50) -> dict[str, Any]:
        from .output import read_meta

        cfg = self.config()
        if not cfg.inbox_dir.exists():
            return {"items": []}
        items = []
        for path in sorted(cfg.inbox_dir.glob("*.md"), reverse=True)[:limit]:
            meta = read_meta(path)
            items.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "title": meta.get("title", path.stem),
                    "date": meta.get("date", ""),
                    "project": meta.get("project", ""),
                    "speakers": meta.get("speakers", []),
                    "date_inferred": str(meta.get("date_inferred", "")).lower() == "true",
                    "size": path.stat().st_size,
                }
            )
        return {"items": items}

    def start_recording(self, body: dict[str, Any]) -> dict[str, Any]:
        from .pipeline import LiveSession

        if self.session is not None:
            raise SaidsoError("Already recording.")
        session = LiveSession(
            self.config(),
            title=body.get("title") or None,
            project=body.get("project") or None,
            link=body.get("link") or "",
            participants=body.get("participants") or [],
        )
        session.start()
        self.session = session
        self.events.emit("recording", state="started", title=session.title)
        return self.recording_status()

    def recording_status(self) -> dict[str, Any]:
        if self.session is None:
            return {"recording": False, "busy": self.busy}
        return {
            "recording": self.session.running,
            "busy": self.busy,
            "title": self.session.title,
            "project": self.session.route.project.key,
            "elapsed": round(self.session.elapsed, 1),
            "mic": self.session.mic.name if self.session.mic else None,
            "system": self.session.system.name if self.session.system else None,
        }

    def stop_recording(self) -> dict[str, Any]:
        if self.session is None:
            raise SaidsoError("Not recording.")
        session, self.session = self.session, None
        self.events.emit("recording", state="stopped")

        def work():
            outcome = session.stop(progress=self._progress())
            return _outcome(outcome)

        self._run("transcribe", work)
        return {"started": True}

    def cancel_recording(self) -> dict[str, Any]:
        if self.session is None:
            raise SaidsoError("Not recording.")
        session, self.session = self.session, None
        session.cancel()
        self.events.emit("recording", state="cancelled")
        return {"cancelled": True}

    def transcribe(self, body: dict[str, Any]) -> dict[str, Any]:
        from .pipeline import transcribe_file

        paths = [Path(p) for p in body.get("paths") or []]
        if not paths:
            raise SaidsoError("No files given.")
        cfg = self.config()
        project = body.get("project") or None

        def work():
            results = []
            for i, path in enumerate(paths, 1):
                self.events.emit("progress", fraction=None,
                                 message=f"{path.name} ({i} of {len(paths)})")
                results.append(_outcome(transcribe_file(
                    cfg, path, project=project, progress=self._progress()
                )))
            return results

        self._run("transcribe", work)
        return {"started": True, "count": len(paths)}

    def sweep(self) -> dict[str, Any]:
        from . import tracker

        report = tracker.sweep_all(self.config())
        return {
            "moved": report.moved,
            "problems": report.problems,
            "index": str(report.index_path or ""),
        }


def _outcome(outcome) -> dict[str, Any]:
    return {
        "transcript": str(outcome.transcript),
        "name": outcome.transcript.name,
        "title": outcome.meta.title,
        "project": outcome.project,
        "segments": outcome.segments,
        "date": outcome.meta.date.isoformat(),
        "date_inferred": outcome.meta.date_inferred,
        "notes": outcome.notes,
    }


class Handler(BaseHTTPRequestHandler):
    engine: Engine
    token: str
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # the shell shows what matters; this would just be noise

    # ------------------------------------------------------------ plumbing

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        return secrets.compare_digest(header, f"Bearer {self.token}")

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as e:
            raise SaidsoError(f"Malformed JSON body: {e}") from e

    def _dispatch(self, routes: dict[str, Any]) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        handler = routes.get(path)
        if handler is None:
            self._send(404, {"error": f"No such endpoint: {path}"})
            return
        try:
            self._send(200, handler())
        except SaidsoError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    # ------------------------------------------------------------ routes

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0].rstrip("/") == "/health":
            self._send(200, {"ok": True, "version": __version__})
            return
        if not self._authorised():
            self._send(401, {"error": "Missing or bad token."})
            return
        if self.path.split("?")[0].rstrip("/") == "/events":
            self._stream()
            return
        self._dispatch(
            {
                "/settings": self.engine.settings,
                "/devices": self.engine.devices,
                "/projects": self.engine.projects,
                "/inbox": self.engine.inbox,
                "/record/status": self.engine.recording_status,
            }
        )

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            self._send(401, {"error": "Missing or bad token."})
            return
        self._dispatch(
            {
                "/settings": lambda: self.engine.update_settings(self._body()),
                "/record/start": lambda: self.engine.start_recording(self._body()),
                "/record/stop": self.engine.stop_recording,
                "/record/cancel": self.engine.cancel_recording,
                "/transcribe": lambda: self.engine.transcribe(self._body()),
                "/tracker/sweep": self.engine.sweep,
                "/shutdown": self._shutdown,
            }
        )

    def _shutdown(self) -> dict[str, Any]:
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        return {"stopping": True}

    def _stream(self) -> None:
        q = self.engine.events.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    data = json.dumps(event, default=_json_default)
                    self.wfile.write(f"data: {data}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")  # keeps proxies and Chrome happy
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.engine.events.unsubscribe(q)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _exit_when_parent_does(server: ThreadingHTTPServer) -> None:
    """Shut down when stdin closes, which happens when the parent process dies.

    Without this, force-killing the desktop shell — or crashing it — leaves the
    engine running unattended. That is not merely untidy: if a recording is in
    progress the orphan keeps holding the microphone, with no window left to
    stop it from.
    """

    def watch() -> None:
        try:
            while sys.stdin.readline():
                pass
        except (OSError, ValueError):
            pass
        server.shutdown()

    threading.Thread(target=watch, daemon=True, name="saidso-parent-watch").start()


def serve(host: str = "127.0.0.1", port: int = 0, token: str | None = None,
          config_path: Path | None = None, exit_with_parent: bool = False) -> None:
    token = token or secrets.token_urlsafe(24)
    handler = type("BoundHandler", (Handler,), {"engine": Engine(config_path), "token": token})
    server = ThreadingHTTPServer((host, port), handler)
    actual = server.server_address[1]

    # The handshake line is how the desktop shell learns the port and token.
    print(json.dumps({HANDSHAKE: __version__, "port": actual, "token": token}), flush=True)
    if exit_with_parent:
        _exit_when_parent_does(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="saidso-server", description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--token", default=None, help="auth token (generated if omitted)")
    parser.add_argument("--config", default=None, help="config file to use")
    parser.add_argument(
        "--exit-with-parent",
        action="store_true",
        help="shut down when stdin closes, i.e. when the process that started this one dies",
    )
    args = parser.parse_args(argv)
    try:
        serve(
            args.host,
            args.port,
            args.token,
            Path(args.config) if args.config else None,
            exit_with_parent=args.exit_with_parent,
        )
    except OSError as e:
        print(f"saidso-server: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
