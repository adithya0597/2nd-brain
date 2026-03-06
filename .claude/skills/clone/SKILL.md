---
name: clone
description: >
  Use this skill when the user wants to duplicate their current conversation
  in full — any request that signals "I want a copy of this entire chat so I
  can branch off or experiment without losing my place." This includes forking
  a conversation, duplicating a session, branching off to try an alternative
  approach, or wanting a safety copy before making risky changes. Creates a
  complete clone of the full conversation history. Distinguished from
  half-clone (which discards the earlier half of the conversation to reduce
  token usage) and from handoff (which writes a summary document for a future
  session rather than duplicating the conversation itself).
---

# Clone Conversation

Clone the current conversation so the user can branch off and try a different approach.

## Steps

1. Get the current session ID and project path:
   ```bash
   tail -1 ~/.claude/history.jsonl | jq -r '[.sessionId, .project] | @tsv'
   ```

2. Find clone-conversation.sh: first check `"$PROJECT_DIR/scripts/clone-conversation.sh"` where PROJECT_DIR is the project path from step 1. If not found, run:
   ```bash
   find ~/.claude -name "clone-conversation.sh" 2>/dev/null | sort -V | tail -1
   ```

3. Run the script:
   ```bash
   <script-path> <session-id> <project-path>
   ```
   Always pass the project path from the history entry, not the current working directory.

4. Tell the user they can access the cloned conversation with `claude -r` and look for the one marked `[CLONED <timestamp>]` (e.g., `[CLONED Jan 7 14:30]`).
