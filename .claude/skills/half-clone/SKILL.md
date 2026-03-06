---
name: half-clone
description: >
  Use this skill when the user wants to continue their conversation but shed
  older context to free up token budget — any request that signals "this
  session is getting long and I want to keep only the recent, relevant part."
  This includes trimming the conversation, reducing context size, cloning just
  the recent half, or feeling that the session is slowing down due to length.
  Copies only the later half of the conversation history, discarding earlier
  turns to reduce token consumption while preserving recent work and momentum.
  Distinguished from full clone (which copies everything without trimming) and
  from handoff (which writes a structured summary for a future session rather
  than preserving actual conversation turns).
---

# Half-Clone Conversation

Clone the later half of the current conversation, discarding earlier context to reduce token usage while preserving recent work.

## Steps

1. Get the current session ID and project path:
   ```bash
   tail -1 ~/.claude/history.jsonl | jq -r '[.sessionId, .project] | @tsv'
   ```

2. Find half-clone-conversation.sh: first check `"$PROJECT_DIR/scripts/half-clone-conversation.sh"` where PROJECT_DIR is the project path from step 1. If not found, run:
   ```bash
   find ~/.claude -name "half-clone-conversation.sh" 2>/dev/null | sort -V | tail -1
   ```

3. Preview the conversation to verify the session ID:
   ```bash
   <script-path> --preview <session-id> <project-path>
   ```
   Check that the first and last messages match the current conversation.

4. Run the clone:
   ```bash
   <script-path> <session-id> <project-path>
   ```
   Always pass the project path from the history entry, not the current working directory.

5. Tell the user they can access the half-cloned conversation with `claude -r` and look for the one marked `[HALF-CLONE <timestamp>]` (e.g., `[HALF-CLONE Jan 7 14:30]`). The script automatically appends a reference to the original conversation at the end of the cloned file.
