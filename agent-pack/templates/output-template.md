# Meeting note template

Use this structure. The headings and their order are the contract — retrieval,
wiki tooling and human readers all depend on files looking the same.

```markdown
---
date: {YYYY-MM-DD}
project: {project key from `saidso projects`}
workstream: {initiative within that project, or omitted}
meeting_type: {standup | planning | review | 1:1 | project-sync | partner-sync | other}
attendees: [{Name}, {Name}]
tags: [{topic-tag}, {topic-tag}, {topic-tag}]
related: []
---

# {Meeting title}

**Date:** {YYYY-MM-DD}
**Duration:** {45 min, or "Not captured"}
**Meeting type:** {Standup | Planning | Review | 1:1 | Project sync | Other}

## Attendees
- {Name} ({role or team, if known})

## Summary
{2-4 sentences. What the meeting was about and the headline outcome. Someone
should be able to read only this and know whether to read further.}

## Discussion
### {Topic}
{Key points, tradeoffs, who raised what. Short paragraphs or a tight list.}

## Decisions
- **{Decision}** — {what was decided and why.}

(If none were made, write "None this meeting." Do not invent them.)

## Agreed upon
- {Informal consensus that isn't a load-bearing decision but should be remembered.}

## Action items
| Owner | Task | Due |
|-------|------|-----|
| {Name} | {Specific deliverable} | {YYYY-MM-DD or "TBD"} |

## Open questions / blockers
- {Raised but unresolved. Include who raised it when that matters.}

## Next steps
- {What happens next at the meeting or project level.}

## Related meetings
- [{previous-note-basename}]({previous-note-basename}.md)

---
*Notes generated from {a saidso transcript | a VTT export | a DOCX transcript | pasted notes}.*
```

## Frontmatter rules

- **`date`** — ISO, and the same date as the body. If the transcript carries
  `date_inferred: true`, the date is a guess from the file's modification time:
  say so in the note and ask for confirmation rather than presenting it as fact.
- **`project` and `workstream` are different axes.** `project` is the business
  or client — one of the keys from `saidso projects`, and it must match the
  folder the note lives in. `workstream` is the initiative inside it ("legacy BI
  migration"). Never put a workstream value in `project`; that conflation
  is the single easiest mistake to make here.
- **`attendees`** — full names, one canonical form per person, as a YAML list
  so each name is a discrete searchable token. Never use a room name.
- **`tags`** — three to five lowercase kebab-case topics drawn from the actual
  Discussion sections. Specific (`search-latency`) beats broad (`engineering`).
  Three sharp tags beat seven fuzzy ones.
- **`related`** — leave `[]` unless you can confidently name a sibling note. A
  bad guess costs more than an empty value.

## Formatting rules

- `##` for sections, `###` for topics inside Discussion. Don't change levels.
- Dates are always ISO. Never "June 1" or "6/1/26".
- Action items go in a table, not bullets.
- One topic per Discussion heading. If the meeting jumped around, restructure
  into clean topics rather than preserving the chronological mess.

## What to leave out

- Timestamps. The date is enough.
- Per-sentence attribution in Discussion. Attribute when it matters —
  disagreement, a commitment, a key insight — not for routine statements.
- Filler from auto-generated recaps ("The team had a great conversation about...").
