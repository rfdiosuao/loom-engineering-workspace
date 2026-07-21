---
name: openclaw-meeting-notes
description: Turn meeting transcripts, call notes, chat logs, or raw discussion notes into concise minutes, decisions, action items, owners, deadlines, and follow-up messages. Use for meeting minutes, meeting summaries, action-item extraction, Chinese office meeting notes, and project sync recaps.
---

# OpenClaw Meeting Notes

Use this skill when the user asks for meeting minutes, meeting summaries, action items, follow-up messages, or project sync recaps.

## Workflow

1. Identify the source type: transcript, voice-to-text output, chat log, rough notes, or agenda.
2. Preserve factual decisions and unresolved questions. Do not invent attendees, owners, deadlines, or decisions.
3. Normalize noisy transcript text before summarizing. Merge repeated speech and remove filler.
4. Produce the most useful office-ready structure:
   - meeting title;
   - date/time if provided;
   - one-paragraph executive summary;
   - decisions;
   - action items with owner and deadline;
   - risks/blockers;
   - follow-up message draft.
5. If owners or deadlines are missing, mark them as "TBD" instead of guessing.

## Output Template

```markdown
# Meeting Notes

## Summary
...

## Decisions
- ...

## Action Items
| Task | Owner | Deadline | Status |
|---|---|---|---|
| ... | TBD | TBD | Open |

## Risks And Blockers
- ...

## Follow-Up Message
...
```

## Quality Bar

- Keep summaries short enough for a manager to scan.
- Keep action items concrete and verb-led.
- Separate confirmed decisions from proposals.
- For Chinese meetings, output polished Chinese unless the user asks otherwise.
