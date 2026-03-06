# P2 Backlog — Second Brain Audit Fixes

Remaining items from the 8-perspective system audit (2026-03-03).
P0 and P1 fixes were implemented on 2026-03-06.

## Robustness

- [ ] **Startup health check** — Validate schema version, required env vars, vault path exists, DB writable at boot. Fail fast with clear error messages. (~3 hrs)
- [ ] **Feedback re-routing** — When user corrects a classification via "Wrong" button, re-post the capture to the correct dimension channel (currently only updates DB). (~2 hrs)

## Content & Prompts

- [ ] **Slack-specific prompt versions** — Create alternate `.claude/commands/brain/slack/` prompt files that reference pre-gathered context instead of MCP tools (which are unavailable in the Slack bot execution path). (~4 hrs)
- [ ] **Populate Values.md + ICOR goals** — User action: fill in `vault/Identity/Values.md` and set active goals in Notion. Without this data, insight commands produce generic output. (~30 min)

## New Features

- [ ] **`/brain-help` command** — Register a help slash command that returns a formatted table of all 14+ commands with descriptions and example usage. (~2 hrs)
- [ ] **`/brain:find` semantic search** — Highest-value missing feature. Use sentence-transformers embeddings (already loaded for classifier) to search vault content by semantic similarity. Return top-N ranked results with snippets. (~1 day)
- [ ] **`/brain:weekly-review` command** — GTD-style weekly review ritual: review completed actions, check stale projects, audit ICOR balance, plan next week. (~1 day)

## Testing

- [ ] **Minimal pytest suite** — Priority test targets: classifier (4-tier pipeline, confidence thresholds), vault_ops (write/read roundtrip, wikilinks), journal_indexer (mood/energy detection, ICOR extraction). Target: 80% coverage on core/. (~1 day)
