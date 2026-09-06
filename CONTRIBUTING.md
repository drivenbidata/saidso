# Contributing

```bash
git clone https://github.com/drivenbidata/saidso
cd saidso
pip install -e ".[all,dev]"
pytest
ruff check .
```

The desktop shell needs Node 20+ and a Python that can import saidso:

```bash
cd desktop && npm install && npm start
```

To build installers — the frozen engine plus the shell around it:

```bash
cd desktop && npm run make      # output in desktop/out/make/
```

## Where things go

| You want to… | Look at |
| --- | --- |
| support a new transcript format | `src/saidso/parse/` |
| add a capture platform | `src/saidso/capture/` — implement `devices()` and `record()` |
| change what a transcript file looks like | `src/saidso/output/markdown.py` |
| change how projects are chosen | `src/saidso/output/routing.py` |
| change tracker behaviour | `src/saidso/tracker/` |
| add a command | `src/saidso/cli.py`, and `server.py` if the window needs it too |
| change how notes are written up | `agent-pack/` — that's a prompt, not code |

## The line this project draws

Rules go in code; judgement goes in a prompt. Naming a file, resolving a
project, stamping a completion date and rebuilding an index are rules — they
must behave identically every time, so they live in Python and have tests.
Deciding what counts as a decision, or who owns an action item, is reading
comprehension, and lives in `agent-pack/` where it can be swapped.

A change that moves work across that line needs a reason in the pull request.

## What tests are for here

Not coverage. Every test in `tests/` pins a behaviour that would be silently
wrong otherwise, and most of them exist because something actually went wrong:

- a transcript shape that lost every speaker label (`test_parse.py`)
- a sweep that ate the blank line after `## Open` (`test_tracker.py`)
- an unattended sync that committed a file's absence as a deletion
  (`test_sync.py`)

If you fix a bug, pin it. If you're adding a feature, test the thing that would
be quietly wrong rather than the thing that would obviously throw.

## Style

- Ruff, 100 columns, and `ruff check .` clean.
- Comments explain *why*, especially where the obvious approach is wrong. There
  are several such places and they are commented deliberately.
- Error messages are user-facing copy. Say what happened and what to do next —
  `SaidsoError` is printed without a traceback for exactly this reason.
- No new required dependencies in the core install without discussion. Optional
  extras are cheap; a core dependency is forever.

## Licence

Contributions are under Apache-2.0, matching the project.
