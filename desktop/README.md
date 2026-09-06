# saidso desktop

An Electron shell over the same engine the CLI drives. It owns no logic of its
own: it starts `python -m saidso.server` as a child process, reads the port and
token from the handshake line the server prints, and proxies requests. Anything
the window can do, `saidso` can do from a terminal.

## Running it

The engine has to be importable by some Python on the machine:

```bash
pip install "saidso[all]"     # from the repository root
cd desktop
npm install
npm start
```

If Python isn't on `PATH`, or the right interpreter isn't the first one found,
point `SAIDSO_PYTHON` at it:

```bash
SAIDSO_PYTHON=C:/Users/you/venv/Scripts/python.exe npm start
```

The window says so plainly when it can't find a usable interpreter, rather than
opening blank.

## What the window can change

The Settings panel writes to the same `config.toml` the CLI reads, so the two
views can't diverge. It exposes only the fields a person can reasonably change
from a window — the notes folder, your speaker name, the model — because a
settings endpoint that can rewrite anything is one that can corrupt anything.
The project list and the rest stay in the file.

## How the pieces fit

```
main.js       spawns the engine, holds the token, proxies /api, forwards events
preload.js    the only bridge into the page: a handful of named functions
renderer/     plain HTML, CSS and JS - no framework, no build step
```

Security posture, which is why there is no bundler here:

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`
- a CSP that allows only same-origin scripts and styles
- the API token never reaches the renderer; main.js does every fetch
- the engine binds to `127.0.0.1` on an ephemeral port and requires that token

The renderer holds no state the engine doesn't also hold. It asks on load and
reacts to events, so closing and reopening the window can't produce a view that
disagrees with what is actually recording.

## Packaging

```bash
npm run make
```

That builds the frozen Python engine first, then packages the shell around it,
leaving installers in `out/make/`. The result needs no Python on the target
machine. See [../packaging/README.md](../packaging/README.md) for how the two
halves meet, what the PyInstaller spec has to be told, and why the engine ships
as a folder rather than a single executable.
