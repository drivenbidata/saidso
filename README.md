# saidso

Record your meetings, transcribe them, and file the transcripts where you can
find them again — entirely on your own machine. Audio never leaves it.

saidso captures your microphone and your system audio as two separate tracks,
transcribes both locally with Whisper, and writes one clean markdown transcript
per meeting into a folder you control. Turning those transcripts into meeting
notes is left to an agent of your choosing; see [agent-pack/](agent-pack/).

> **Status: alpha.** The engine, the CLI and the desktop app work end to end,
> and package into an installer that needs no Python. Live capture is
> Windows-only so far, behind an interface that makes macOS and Linux a
> single-file addition. Builds are unsigned, so expect a SmartScreen or
> Gatekeeper warning.

## Why it works this way

**Two tracks, not a mix.** Your microphone is you; the loopback is everyone
else. Recording them separately means your own speech is labelled with
certainty and no model at all — so speaker diarisation stays optional, needed
only to split the *other* track into individuals.

**Rules in code, judgement in a model.** Naming a file, deciding which project
a transcript belongs to, stamping a completion date, rebuilding an index — all
rules, and they live in saidso where they run identically every time. Deciding
what counts as a decision, who owns an action item, or whether two people
actually disagreed is reading comprehension, and that lives in a prompt you can
swap. The line between them is deliberate.

**Guesses are labelled as guesses.** A date taken from a filename is a fact. A
date taken from a file's modification time is a guess — for a downloaded
transcript it is the download date, not the meeting date, and a whole batch
downloaded together will share one. saidso writes `date_inferred: true` when
it had to guess, and says so on the way past.

## Install

**The desktop app** — an installer that needs nothing preinstalled, no Python
included. Built with `npm run make` in [desktop/](desktop/); see
[packaging/README.md](packaging/README.md).

**The CLI and library** — requires Python 3.11+.

```bash
pip install saidso[all]      # everything, including local transcription
pip install saidso           # core only: parsing, routing, trackers, sync
```

Extras, if you'd rather be specific:

| Extra | Gives you |
| --- | --- |
| `transcribe` | local transcription (faster-whisper) |
| `capture` | live recording on Windows (PyAudioWPatch) |
| `docx` | reading `.docx` transcript exports |
| `diarize` | splitting other participants into Speaker 1/2/… (pyannote) |

The first transcription downloads the Whisper model (~150 MB for `base`).

## Verifying a download

Releases are unsigned, so Windows and macOS will warn. Every installer ships
with a SHA256SUMS file and a GitHub build provenance attestation, so you can
confirm a binary is the one this repository's workflow built:

```bash
gh attestation verify saidso-setup.exe --repo drivenbidata/saidso
```

## Quick start

```bash
saidso init --name "Your Name"      # config + notes folder
saidso devices                      # check the mic and loopback it picked
saidso record --name "Weekly Sync"  # Enter to stop and transcribe
```

Already have recordings or exports?

```bash
saidso transcribe meeting.mp4               # any audio or video file
saidso watch ~/Downloads/recordings         # transcribe anything dropped there
saidso parse teams-export.vtt               # clean Speaker: text, for a model
```

## Commands

`saidso <command> --help` gives the full flags for any of these.

| Command | What it does |
| --- | --- |
| `init` | Write the config and create the notes folder. `--notes-dir`, `--name`, `--force`. |
| `devices` | List microphones and system-audio inputs, marking the defaults. |
| `record` | Record a meeting; Enter stops and transcribes, Ctrl+C discards. |
| `transcribe` | Transcribe audio or video files, or a folder of them. |
| `ingest` | File an existing transcript — a `.vtt`, `.docx`, `.md` or `.txt` export. |
| `watch` | Transcribe anything dropped into a folder, moving handled files aside. |
| `parse` | Print a clean `Speaker: text` log to stdout. `--speakers` for just the names. |
| `projects` | List configured projects and which is the default. |
| `tracker sweep` | Move ticked items into Completed and rebuild the index. `--dry-run`. |
| `tracker add` | Insert a meeting and its items under `## Open`. |
| `sync` | Pull, stage, guard, commit, push. `-m`, `--no-push`, `--dry-run`. |
| `config show` / `path` | Print the config, or where it lives. |

Flags shared by most commands: `--project KEY` to override routing, `--config FILE`
and `--notes-dir DIR` to work against a different setup, `-q` to silence progress.

### The three ways material comes in

```bash
saidso record --name "Weekly Sync"     # a meeting happening now
saidso transcribe recording.mp4        # audio or video, transcribed locally
saidso ingest teams-export.vtt         # a transcript some other tool produced
```

All three end the same way: one markdown transcript in `inbox/`, with the same
frontmatter, routed to the same projects. Nothing downstream can tell which
route a transcript took.

`ingest` leaves your original file exactly where it is, and writes the dialogue
without timestamps — an export's cue times describe cue boundaries rather than
speaking turns, and inventing plausible-looking times would be worse than
having none.

## What you get

```
<notes_dir>/
├── inbox/            transcripts, waiting to be turned into notes
├── processed/        raw transcripts already written up
├── <project>/        your notes, and that project's Tracker.md
└── Tracker.md        index only — counts per project, never items
```

A transcript looks like this. The frontmatter is the point: it is what an agent
filters on and what you search six months later.

```markdown
---
title: Weekly Sync
date: 2026-09-01
project: acme
source: live recording
duration: "00:47:12"
language: en
speakers: [Javi Gold, Speaker 1]
generator: saidso 0.1.0
---

# Weekly Sync — Raw Transcript

[00:00:04] **Javi Gold:** Morning everyone, let's get going.
[00:00:15] **Speaker 1:** I have an update on the bronze tables.
```

One line per turn, so grep works and diffs read cleanly.

## Projects

A project is a destination: a client, a side venture, a job. Transcripts route
to one automatically — by an explicit `--project`, then the transcript's own
frontmatter, then a project key leading the filename, then your default.

```toml
default_project = "acme"

[[projects]]
key = "acme"
label = "Acme Corp"
folder = "acme"
```

Adding one is a config edit and nothing else. A filename token that *nearly*
matches a key — `acmé` for `acme` — stops the run and asks rather than falling
through to the default, because a misfiled meeting is expensive precisely
because nobody notices it.

## Action trackers

Each project keeps a `Tracker.md` with `## Open` and `## Completed`. Your agent
adds items under Open. You tick them off in any editor. saidso does the rest:

```bash
saidso tracker sweep
```

Ticked items move to Completed, reformatted to stand alone, stamped with the
date — or with an explicit `· done: 2026-09-03` you wrote yourself, since a
Friday tick would otherwise be recorded as Monday. Finished meetings drop out
of Open, and the root index is rebuilt.

Every sweep is validated against the file it started from: counts must move by
exactly the number of items, no ticked item may remain under Open, untouched
text must be untouched. If any check fails, the file is left exactly as it was
and the reason is reported. A tracker that didn't get swept is an annoyance; a
mangled one loses work.

## Optional git sync

```toml
[sync]
enabled = true
remote = "origin"
branch = "main"
```

`saidso sync` pulls, stages only the paths saidso owns, and **refuses to commit
a deletion it didn't make**. That guard is the whole reason this feature is
written the way it is: the pipeline saidso grew out of lost a meeting note to
an unattended `git add -A` that ran before its pull, committing a file's
absence as a deletion. Pulling first prevents the class; refusing surprise
deletions catches the rest. Set `allow_deletions = true` if you genuinely
delete notes and want that mirrored.

saidso never writes credentials to disk. Whatever git already uses for that
repository is what it uses.

## Turning transcripts into notes

That part is yours to choose. [agent-pack/](agent-pack/) ships a Claude skill,
a provider-neutral prompt, and the note template — including the synthesis
rules that matter most: keep *discussed*, *agreed*, *decided* and *action*
distinct; give every action item an owner; preserve figures and table names
verbatim; and never smooth two unresolved positions into a false consensus.

```bash
cp -r agent-pack/skills/saidso-meeting-notes ~/.claude/skills/
# then: "process the inbox"
```

## Platform support

| | Transcribe files | Live capture |
| --- | --- | --- |
| Windows | yes | yes (WASAPI loopback) |
| macOS | yes | not yet — needs ScreenCaptureKit or a virtual device |
| Linux | yes | not yet — PipeWire/PulseAudio monitor sources |

Capture sits behind one small interface; adding a platform means implementing
`devices()` and `record()` in a single file. See
[src/saidso/capture/](src/saidso/capture/) — the macOS and Linux stubs document
what each needs.

## Configuration

One TOML file. The desktop app can change the notes folder and your speaker
name directly; everything else is edited in the file.

`saidso config path` prints where it lives —
`%APPDATA%\saidso\config.toml` on Windows, `~/.config/saidso/` on Linux,
`~/Library/Application Support/saidso/` on macOS. Set `SAIDSO_HOME` to override.

```toml
notes_dir = "C:/Users/you/notes"
default_project = "acme"

[identity]
name = "Your Name"          # your speaker tag on the microphone track

[transcribe]
model = "base"              # tiny | base | small | medium | large-v2 | large-v3
language = ""               # "" = auto-detect
diarize = false

[capture]
mic = ""                    # device index or name fragment; "" = system default
system = ""
keep_audio = false

[output]
flavor = "plain"            # or "obsidian", for wiki-links
```

## Troubleshooting

Every entry here was hit for real.

**`saidso: command not found` after `pip install`**
The script installed somewhere that isn't on your `PATH` — common with the
Microsoft Store build of Python, which puts scripts under
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python…\LocalCache\local-packages\Python3xx\Scripts`.
Find it with `python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"`,
or skip the problem entirely with `python -m saidso.cli …`.

**The desktop app says "No saidso engine found"**
You are running from source without an engine. Either build one
(`npm run build:engine`) or install the package so some Python can import it
(`pip install "saidso[all]"`). If the wrong interpreter is first on your `PATH`,
point `SAIDSO_PYTHON` at the right one. A packaged build ships its own engine
and never sees this.

**Windows says "Windows protected your PC", macOS says the developer can't be verified**
The builds are unsigned. On Windows: *More info → Run anyway*. On macOS:
right-click the app → *Open*. See [Verifying a download](#verifying-a-download)
for how to confirm a binary is genuine without a certificate.

**Nothing was recorded, or only your own voice**
Run `saidso devices` and check the system-audio entry is a **loopback** device.
Loopback captures what the machine plays, which is everyone else on the call —
without it you record only your microphone. Set `capture.system` in the config
to a name fragment of the right device. Note that a loopback delivers nothing at
all while the machine is silent, so a recording made with everything muted is
correctly empty rather than broken.

**`… isn't a recognised audio or video file`**
It is probably already a transcript. `saidso transcribe` is for media;
`saidso ingest` is for `.vtt`, `.docx`, `.md` and `.txt`.

**A run stopped with "very close to <project>"**
A filename began with something one character away from a project key. That is
deliberate: a misfiled meeting is expensive precisely because nobody notices.
Rename the file, or say which you meant with `--project`.

**Dates are wrong on a batch of downloaded transcripts**
Look for `date_inferred: true` in the frontmatter. It means the date came from
the file's modification time, which for a download is the *download* date — so a
batch fetched together all look like the same day. Put the real date in the
filename (`2026-09-01_Weekly-Sync.vtt`) or pass `--date`, and it becomes
authoritative.

**Speakers are "Others" instead of names**
Diarisation is off or unavailable. It is optional by design; your own track is
always labelled correctly without it. To split the other participants, install
`pip install "saidso[diarize]"`, set `SAIDSO_HF_TOKEN`, and accept the model
terms on Hugging Face. `saidso transcribe --diarize` says why it skipped.

**`saidso sync` refused to commit a deletion**
Working as intended. An unattended sync should almost never delete a note, and
this guard exists because one silently did. Find out what is missing and why —
another machine may have created it — before setting `sync.allow_deletions`.

**`saidso tracker sweep` reported REFUSED and changed nothing**
The rewrite failed its own validation, so the tracker was left exactly as it
was. Nothing is lost. The message names the check that failed; the usual cause
is hand-editing that made the Open and Completed sections inconsistent.

**The first transcription takes a long time**
It downloads the Whisper model (~150 MB for `base`) into your cache. Subsequent
runs reuse it. `--model tiny` is much smaller and quicker if you just want to
see it work.

**A packaged build hangs with no error at all**
Get a stack out of it — a frozen app has no traceback otherwise:
```bash
SAIDSO_STACK_AFTER=40 saidso-engine.exe --port 0
```
Every thread's stack goes to stderr after 40 seconds, repeatedly. See
[packaging/README.md](packaging/README.md).

## Development

```bash
pip install -e ".[all,dev]"
pytest
ruff check .
```

The layout:

```
src/saidso/
├── capture/     audio off the machine, per platform
├── transcribe/  audio -> timed segments, plus optional diarisation
├── parse/       any transcript format -> clean Speaker: text
├── output/      segments -> a filed markdown transcript
├── tracker/     the deterministic half of action tracking
├── sync/        optional, guarded git mirroring
├── pipeline.py  what the CLI and desktop app both drive
└── cli.py       the command line
```

The CLI and the desktop app call the same functions in `pipeline.py`, so the
two can't drift: anything you can do in the window you can script.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
