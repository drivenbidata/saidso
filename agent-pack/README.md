# agent-pack

saidso stops at a clean, well-named, correctly filed transcript. Turning that
into a meeting note takes reading comprehension, so it is left to an agent you
choose — and this folder is what you give it.

```
skills/saidso-meeting-notes/SKILL.md   a Claude skill: the full workflow
prompts/meeting-notes.md               provider-neutral system prompt
templates/output-template.md           the note structure and frontmatter rules
```

## Why this isn't built in

Two reasons, and the second is the real one.

Summarisation quality is the whole value of a meeting note, and it moves fast.
Pinning saidso to one provider would date the tool and force an API key on
people who installed it precisely because their audio never leaves the machine.

More importantly, the split is honest about where judgement lives. Deciding
what counts as a decision, who owns an action, and whether two people actually
disagreed is reading comprehension. Naming a file, resolving a project,
stamping a completed date and rebuilding an index are rules. Rules belong in
code, where they run identically every time; judgement belongs to a model you
can swap. Everything in saidso proper is on the rules side of that line.

## Using it with Claude Code

Copy the skill into your skills directory:

```bash
cp -r agent-pack/skills/saidso-meeting-notes ~/.claude/skills/
```

Then say "process the inbox". The skill drives the `saidso` CLI — `saidso
parse`, `saidso projects`, `saidso tracker add`, `saidso sync` — rather than
reaching into your files directly, so it stays correct as saidso changes.

## Using it with anything else

Give the model `prompts/meeting-notes.md` as its system prompt and
`templates/output-template.md` as the required output shape, then feed it:

```bash
saidso parse "<notes_dir>/inbox/2026-09-01_acme_Weekly-Sync.md"
```

That prints a clean `Speaker: text` log with timestamps, frontmatter, platform
chatter and formatting removed, and contiguous turns merged — which is the form
a model reads best. `--speakers` prints just the attendee list.

Write the result to `<notes_dir>/<project>/`, add owned items with `saidso
tracker add`, and move the raw file to `processed/`.

## The one rule for whatever you build

Let saidso own `## Completed` and the root index. `saidso tracker sweep` moves
ticked items across with the correct date and attribution, drops finished
meetings, validates the result, and refuses to write anything that doesn't
validate. An agent writing those sections directly loses all of that.
