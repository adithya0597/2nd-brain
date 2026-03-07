# /brain:find — Semantic Vault Search

> **Note:** This prompt is used for `/brain-find --ai` mode only. The default `/brain-find` uses fast hybrid search (no AI call).

Search across the entire Second Brain — vault files, SQLite database, and knowledge graph — to find notes, concepts, journal entries, and action items matching a query.

## Instructions

You have been given pre-gathered search results from the database in the Context Data section. Analyze these results and present a ranked, organized response.

### Ranking Priority

1. **Exact title matches** (concept or vault_index title matches query) — highest
2. **Content matches** (journal content, vault file content) — high
3. **Summary matches** (concept or journal summary) — medium
4. **Action item matches** — medium
5. **Graph-adjacent results** (linked from matching files) — lower

### Output Format

Present results grouped by source type. Use concise Slack-formatted markdown:

**Search Results: "[query]"**

**Concepts:**
- [Title] (status, N mentions) — summary snippet

**Journal Entries:**
- [Date]: summary snippet (matched in content/summary)

**Vault Files:**
- [File path] (type, last modified) — title

**Action Items:**
- [Description] (status, date, ICOR element)

**Related (Graph-Adjacent):**
- [Title] — connected via [linking file]

End with a total count: "Found N direct + N related results."

If no results found, say so clearly and suggest broadening the search terms or checking spelling.

### Important Notes

- Do NOT use any MCP tools or external APIs — all data is pre-gathered in context
- Keep snippets short (under 100 chars)
- Deduplicate results that appear in multiple sources
- Highlight the most relevant result at the top
