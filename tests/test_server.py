"""The local API is what the desktop shell talks to, so its contract is tested
the way the shell uses it: over a real socket, with a real subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from saidso import config as config_mod

HANDSHAKE = "saidso-server"


@pytest.fixture
def engine(tmp_path):
    """A running server, with its own config, torn down by closing stdin."""
    home = tmp_path / "home"
    home.mkdir()
    config_mod.starter(notes_dir=tmp_path / "notes").save(home / "config.toml")

    env = {**os.environ, "SAIDSO_HOME": str(home), "PYTHONPATH": str(Path("src").resolve())}
    proc = subprocess.Popen(
        [sys.executable, "-m", "saidso.server", "--port", "0", "--exit-with-parent"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    try:
        handshake = json.loads(proc.stdout.readline())
        assert handshake[HANDSHAKE]
        yield handshake
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _get(engine, path, token=True):
    request = urllib.request.Request(f"http://127.0.0.1:{engine['port']}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {engine['token']}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def test_handshake_carries_a_real_port_and_a_generated_token(engine):
    assert engine["port"] > 0
    assert len(engine["token"]) >= 20  # generated, not guessable


def test_health_needs_no_token(engine):
    status, body = _get(engine, "/health", token=False)
    assert status == 200 and body["ok"]


def test_everything_else_requires_the_token(engine):
    """This API can start recording, so an unauthenticated caller gets nothing."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(engine, "/settings", token=False)
    assert caught.value.code == 401


def test_settings_and_projects_come_from_the_config(engine):
    _, settings = _get(engine, "/settings")
    assert settings["version"]
    assert settings["notes_dir"]

    _, projects = _get(engine, "/projects")
    assert projects["default"] == "general"
    assert [p["key"] for p in projects["projects"]] == ["general"]
    # Resolved, not the raw stored field, which is empty when it defaults.
    assert projects["projects"][0]["tracker"] == "general/Tracker.md"


def _post(engine, path, body):
    request = urllib.request.Request(
        f"http://127.0.0.1:{engine['port']}{path}", method="POST"
    )
    request.add_header("Authorization", f"Bearer {engine['token']}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, json.dumps(body).encode(), timeout=15) as response:
        return json.loads(response.read())


def test_settings_can_be_changed_from_the_window(engine, tmp_path):
    """A desktop user has no other way to move their notes folder."""
    target = tmp_path / "Somewhere Else"
    updated = _post(engine, "/settings", {"notes_dir": str(target), "speaker_name": "Javi Gold"})
    assert Path(updated["notes_dir"]) == target
    assert updated["speaker_name"] == "Javi Gold"
    assert target.is_dir(), "the folder should be created, not just recorded"

    # Written through to the same config.toml the CLI reads, not held in memory.
    assert Path(_get(engine, "/settings")[1]["notes_dir"]) == target


def test_settings_rejects_values_that_would_break_the_config(engine, tmp_path):
    for bad in ({"notes_dir": "   "}, {"model": "enormous"}):
        with pytest.raises(urllib.error.HTTPError) as caught:
            _post(engine, "/settings", bad)
        assert caught.value.code == 400


def test_settings_refuses_a_file_as_the_notes_folder(engine, tmp_path):
    a_file = tmp_path / "not-a-folder.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(urllib.error.HTTPError) as caught:
        _post(engine, "/settings", {"notes_dir": str(a_file)})
    assert "not a folder" in json.loads(caught.value.read())["error"]


def test_concurrent_device_queries_do_not_kill_the_engine(engine):
    """Two threads inside PortAudio's initialise is an access violation, not a
    race with a wrong answer — it killed the whole process, and the window hit
    it on every launch by refreshing twice."""
    import threading

    results: list[object] = []

    def hit():
        try:
            results.append(_get(engine, "/devices")[0])
        except Exception as exc:  # noqa: BLE001 - the failure is the point
            results.append(exc)

    threads = [threading.Thread(target=hit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert results == [200, 200, 200, 200], results
    # and it is still serving afterwards
    assert _get(engine, "/health", token=False)[0] == 200


def test_unknown_endpoints_are_json_not_html(engine):
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(engine, "/nope")
    assert caught.value.code == 404
    assert json.loads(caught.value.read())["error"]


def test_a_bad_request_is_reported_without_crashing_the_server(engine):
    request = urllib.request.Request(
        f"http://127.0.0.1:{engine['port']}/record/stop", method="POST"
    )
    request.add_header("Authorization", f"Bearer {engine['token']}")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 400
    assert "Not recording" in json.loads(caught.value.read())["error"]

    # still serving afterwards
    assert _get(engine, "/health", token=False)[0] == 200


def test_first_launch_creates_a_config_instead_of_erroring(tmp_path):
    """Someone who installs the desktop app and never opens a terminal must get
    a working app, not an error telling them to run a command."""
    home = tmp_path / "fresh"
    home.mkdir()
    assert not (home / "config.toml").exists()

    env = {**os.environ, "SAIDSO_HOME": str(home), "PYTHONPATH": str(Path("src").resolve())}
    proc = subprocess.Popen(
        [sys.executable, "-m", "saidso.server", "--port", "0", "--exit-with-parent"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    try:
        handshake = json.loads(proc.stdout.readline())
        request = urllib.request.Request(f"http://127.0.0.1:{handshake['port']}/projects")
        request.add_header("Authorization", f"Bearer {handshake['token']}")
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
        assert body["default"] == "general"
        assert (home / "config.toml").exists(), "the config should be written, not just held"
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_the_engine_exits_when_its_parent_does(tmp_path):
    """An orphaned engine could keep holding the microphone with no window to stop it."""
    home = tmp_path / "home"
    home.mkdir()
    config_mod.starter(notes_dir=tmp_path / "notes").save(home / "config.toml")
    env = {**os.environ, "SAIDSO_HOME": str(home), "PYTHONPATH": str(Path("src").resolve())}
    proc = subprocess.Popen(
        [sys.executable, "-m", "saidso.server", "--port", "0", "--exit-with-parent"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    json.loads(proc.stdout.readline())
    assert proc.poll() is None

    proc.stdin.close()  # what a dead parent looks like from here
    deadline = time.time() + 15
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.1)
    assert proc.poll() == 0, "the engine outlived its parent"
