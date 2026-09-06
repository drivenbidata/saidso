---
name: "saidso-meeting-notes"
description: "Turn raw meeting transcripts into structured markdown notes, filed by project, and add the user's action items to that project's tracker. Use whenever the user shares a transcript (a saidso .md, a VTT or DOCX export, plain text, or an auto-generated meeting recap) and wants meeting notes, a summary, an action-item list, or a wiki page produced from it — even if they only say 'summarize this meeting' or 'turn this into a doc'. Also use when they ask to process the inbox, drain the transcript queue, catch up on unprocessed meetings, or add meeting actions to a tracker. Output is one markdown note per meeting in the project's folder with YAML frontmatter, tracker entries for anything the user owns, and the raw transcript moved to the processed archive."
---

# saidso meeting notes

You turn raw meeting material into clean, useful markdown notes, filed by
project. The goal is a note a colleague who missed the meeting can actually
use — not a dump of the transcript.

saidso has already done the mechanical half: recording, transcription, naming,
routing and the tracker plumbing. Your half is the part that needs reading
comprehension. Don't reimplement saidso's half — call it.

## Learn the layout from the tool, not from this file

Never hardcode paths or project keys. Ask:

```bash
saidso config show          # notes_dir, inbox, processed, projects, flavor
saidso projects             # the project keys, labels and folders
```

The layout under the notes directory:

```
<notes_dir>/
├── inbox/            raw transcripts waiting to be processed (flat, no subdirs)
├── processed/        raw transcripts already turned into notes — an archive
├── <project>/        finished notes + Tracker.md for that project
└── Tracker.md        index only; counts per project, never items
```

## Two ways this runs

**Inbox mode (the default).** "Process the inbox", "any new transcripts?",
"drain the queue". Work through every raw file in `inbox/`.

**Ad-hoc mode.** The user pastes or attaches a transcript. There is nothing to
move; write the note, update the tracker, and skip the file plumbing.

Both use the same synthesis rules. Only the file handling differs.

## Inbox workflow

1. **List the queue and read the config.**

   ```bash
   saidso config show
   ls "<notes_dir>/inbox"
   ```

   Transcripts arrive as `.md` (saidso's own output), or `.vtt`, `.docx` and
   `.txt` from meeting platforms. **A `.md` file in `inbox/` is a raw
   transcript, not a finished note.** Leave anything that clearly isn't a
   transcript where it is. If the inbox is empty, say so and stop — don't
   invent work.

   **`inbox/` has no subdirectories.** If you find one, move its contents to
   the top-level `processed/` and remove it; transcripts have been orphaned in
   a nested folder before.

2. **Say what you found before starting.** List the filenames, the project each
   resolves to, and how many you're about to process. A four-transcript run is
   long and the user should know the scope up front.

3. **Process one file at a time, start to finish.** Parse, resolve, synthesize,
   write the note, update the tracker, move the raw file — then the next one.
   An interruption then leaves a consistent set of files rather than a
   half-migrated mess.

4. **Parse it.**

   ```bash
   saidso parse "<notes_dir>/inbox/<file>" > /tmp/clean.txt
   saidso parse "<notes_dir>/inbox/<file>" --speakers
   ```

   Handles `.vtt`, `.docx`, `.md` and `.txt`: strips frontmatter, timestamps in
   every shape, emphasis, headings, tables and platform chatter, then merges
   contiguous turns per speaker. For a long transcript, read the output in
   chunks rather than skimming — the substance is often in the back half.

   If the output is a single `(unattributed)` line, the source had no speaker
   structure. The content is still usable; say so plainly in the note and don't
   invent attribution or an attendee list.

5. **Check whether the meeting is already documented.** Before synthesizing,
   search the project folder for distinctive markers — the attendee
   combination, a workstream name, a specific figure or ticket ID. Raw
   transcripts sometimes arrive *after* a note already exists, and a filename
   collision won't catch it because a regenerated title differs. If you find
   one, ask whether to archive the raw file as-is or regenerate.

6. **Confirm the project.** The transcript's frontmatter carries `project:`,
   which saidso resolved when it wrote the file. Trust it unless the content
   plainly contradicts it — and if it does, ask rather than moving the file.

7. **Resolve the date.** The frontmatter has it. If it also has
   `date_inferred: true`, the date is a guess from the file's modification
   time — which for a downloaded transcript is the *download* date. Read the
   dialogue for something better ("have a good weekend" means Friday; "moved to
   Thursday" plus a known download date pins Thursday), and if you improve on
   it, say which reasoning you used. Never present a derived date as fact and
   never rename a file to fix a date without asking.

8. **Synthesize** using `templates/output-template.md` and the principles in
   `prompts/meeting-notes.md`.

9. **Write the note** into the project's folder as
   `<project>-<kebab-title>-<YYYY-MM-DD>.md`. The prefix repeats the folder
   deliberately: it keeps filenames unambiguous in search and in wiki-links,
   which resolve by basename. Don't double the token if the title already
   begins with the project name. If a file of that name exists, ask whether to
   overwrite, merge or skip — never clobber it.

10. **Move the raw file to `processed/`**, keeping its original filename so it
    traces back to the note.

11. **Add the user's items to the tracker.**

    ```bash
    saidso tracker add --project <key> \
      --heading "[[<note-basename>|<Meeting Title>]]" \
      --item "The specific thing to do · due: TBD" \
      --date <YYYY-MM-DD>
    ```

    Use `saidso tracker add` rather than editing `Tracker.md` yourself — it
    inserts under `## Open` without touching anything else, and the sweep that
    later moves ticked items depends on the exact format.

12. **Sync, if the user has it configured.**

    ```bash
    saidso sync -m "Add notes for <N> meetings: <short-title>, <short-title>"
    ```

    If sync refuses because of a staged deletion, **do not override it.** That
    guard exists because an unattended sync once silently deleted a note.
    Investigate what's missing and why, and report it.

13. **Report.** Say what was written and where, flag every note whose date you
    inferred, and give the tracker count per project.

## What belongs in the tracker

Only what the user owns:

- Action items where they are the owner, including jointly — note the
  collaborator, `(with Sam Patel)`.
- Items where they are the likely-but-unconfirmed owner; carry the `(?)`
  through from the note.
- Open questions **they** need to resolve, rephrased as actions ("Resolve
  whether X…") so every line is something that can be finished and ticked.

Not other people's items, and not unassigned questions. Those live in the note.

Each line must stand alone — the tracker is read without the note open, so
"Review the doc" is useless where "Review the Confluence page and SharePoint
docs Priya shared" is not.

**Never write to `## Completed`.** That section belongs to `saidso tracker
sweep`, which moves ticked items across with the right date and attribution.
**Never add items to the root `Tracker.md`** — it is an index, regenerated in
full on every sweep, so anything written there is lost.

## Synthesis principles

The full set is in `prompts/meeting-notes.md`. The ones that matter most:

- Keep *discussed*, *agreed*, *decided* and *action* distinct.
- Every action item has an owner; `(?)` for likely, `Unassigned` for none — and
  an unassigned action item also goes under Open questions.
- Preserve specifics verbatim: table names, ticket numbers, figures.
- Don't smooth over disagreement. Record both positions under Open questions.
- Record what was noticed but not diagnosed.
- Cut social conversation, and note at the foot that you did.
- Empty sections are honest signal. "None this meeting" beats an invention.
- Everything must trace back to something said in the meeting.

## Frontmatter is the most important part of the file

It is what retrieval filters on. `project` is the business or client and must
match the folder; `workstream` is the initiative within it. Conflating the two
is the easiest mistake available here. Tags do the heavy lifting — three to
five specific, lowercase, kebab-case topics drawn from the actual discussion.
Attendees are a YAML list so each name is a discrete token.
