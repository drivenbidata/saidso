# Packaging

The goal is an installer that needs nothing preinstalled — no Python, no pip,
no model runtime. Two builds, in order:

```bash
# 1. freeze the engine (from the repository root)
python -m PyInstaller packaging/saidso-engine.spec --noconfirm \
    --distpath dist/engine --workpath build/pyinstaller

# 2. package the shell around it
cd desktop && npm install && npm run make
```

`npm run make` runs both — step 1 is its `build:engine` script — and leaves
installers in `desktop/out/make/`.

## How the two halves meet

The frozen engine is a **one-folder** bundle, `dist/engine/saidso-engine/`.
One-file was rejected deliberately: a single executable unpacks hundreds of
megabytes to a temp directory on every launch, which makes the app slow to open
and leaves debris behind when it is killed.

Electron Forge copies that folder in as an `extraResource`, so in an installed
app it sits at `resources/saidso-engine/` next to the asar. It stays outside the
asar because it contains native libraries, and those have to be real files on
disk for the loader to find them.

`main.js` looks for the engine in this order:

1. `resources/saidso-engine/` — a packaged app
2. `../dist/engine/saidso-engine/` — a developer checkout that has built one
3. `SAIDSO_PYTHON`, then `python`/`py`/`python3` — probed with a real
   `import saidso`, not merely tested for existence

So the same `main.js` runs from source and from an installer, and a developer
who has not built an engine still gets a working app from their pip install.

## What the spec has to be told

Three packages defeat static analysis and are collected wholesale:

| Package | Why |
| --- | --- |
| `ctranslate2` | native DLLs the Whisper runtime loads at import |
| `av` | bundled ffmpeg libraries for decoding media |
| `faster_whisper` | the Silero VAD weights, loaded as a data file |

`saidso`'s own submodules are collected too. The package imports them lazily so
that a missing optional dependency degrades cleanly instead of breaking
startup — which also hides them from the analysis.

## The import that deadlocks

Worth knowing before changing `engine_entry.py`, because the failure gives you
nothing to go on.

saidso imports faster-whisper **lazily**, so the CLI starts fast and a missing
optional dependency degrades cleanly instead of breaking startup. In a frozen
build that backfires: the first import then happens on a *worker thread*, when
a transcription is requested — and loading numpy's native extension from a
non-main thread deadlocks against the Windows loader lock.

The symptom is a transcription that never starts, never fails, and writes
nothing to stderr. The engine stays responsive, so nothing looks broken. It
reproduces only in the frozen build, never from source.

`engine_entry.py` therefore imports the runtime on the main thread before the
server starts. That is the whole fix, and it must stay: moving the pre-import
into a thread, or removing it because "the lazy import already handles it",
brings the hang straight back.

## Diagnosing a frozen build

A frozen app is a black box — no interpreter to attach to, no traceback for a
hang. So `faulthandler` is always enabled, and:

```bash
SAIDSO_STACK_AFTER=40 dist/engine/saidso-engine/saidso-engine.exe --port 0
```

dumps every thread's stack to stderr after 40 seconds, repeatedly. That is what
identified the deadlock above: one stack frame showing `create_module` stuck on
numpy's `multiarray`, called from a worker thread.

## Size, and the model

The bundle is large: a Whisper runtime with its native libraries is simply not
small. **Model weights are not included** — the first transcription downloads
them (~150 MB for `base`) into the user's cache. Shipping them would multiply
the installer size while forcing one model choice on everyone.

## Signing

Not configured. Unsigned builds mean SmartScreen on Windows and Gatekeeper on
macOS will warn, which is expected for an alpha. Signing needs certificates
that belong to whoever publishes the releases, so it is left to them:
`packagerConfig.osxSign` / `osxNotarize`, and a `certificateFile` on the
Squirrel maker.

What the release workflow does instead costs nothing and is worth having even
once signing exists:

- **SHA256SUMS** beside the installers, so a download can be checked by hand.
- **Build provenance attestations**, which let anyone confirm a binary came out
  of this repository's workflow at a particular commit:

  ```bash
  gh attestation verify saidso-setup.exe --repo drivenbidata/saidso
  ```

Neither stops the operating system warning — only a certificate does that. They
answer a different question: not "is this publisher trusted" but "is this the
file the build produced, unaltered." A checksum with no attestation is weak,
because whoever could replace the binary could replace the checksum too; the
attestation is signed by GitHub and cannot be forged that way.

## Platform notes

Builds are not cross-platform: PyInstaller freezes for the machine it runs on,
so each installer has to be produced on its own operating system. The release
workflow does this with a matrix. macOS and Linux builds package and run, but
live capture is Windows-only for now — those builds transcribe files.
