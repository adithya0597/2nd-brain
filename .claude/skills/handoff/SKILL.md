---
name: handoff
description: >
  Use this skill when the user wants to preserve the current session's state
  for a future agent or session — any request that signals "I'm about to stop
  and want the next session to pick up where I left off." This includes saving
  progress before ending a session, writing a handoff document, preparing for
  a context switch, documenting what was tried and what comes next, or
  approaching the context limit and needing to capture state. Creates or
  updates a HANDOFF.md with goals, progress, what worked, what didn't, and
  numbered next steps. Distinguished from clone/half-clone (which duplicate
  the actual conversation for branching, not summarize state) and from
  review-claudemd (which improves project instructions, not session state).
---

# Write Handoff Document

Write or update a handoff document so the next agent with fresh context can continue this work.

## Steps

1. Check if `HANDOFF.md` already exists in the project root.
2. If it exists, read it first to understand prior context before updating.
3. Create or update the document with these sections:

   - **Goal**: What we're trying to accomplish
   - **Current Progress**: What's been done so far (with file paths)
   - **What Worked**: Approaches that succeeded
   - **What Didn't Work**: Approaches that failed (so they're not repeated)
   - **Outreach Status**: Current state of outreach pipeline (who's been contacted, who's pending)
   - **Notion CRM State**: Last known state of the Notion database (how many entries, last update)
   - **Active Scan State**: Last scan timestamp, which portals were covered, any new companies found
   - **Next Steps**: Clear, numbered action items for continuing
   - **Open Questions**: Anything unresolved that needs user input

4. Save as `HANDOFF.md` in the project root.
5. Tell the user the file path so they can start a fresh conversation with: `claude -r` or reference the file directly.
