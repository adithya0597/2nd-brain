---
name: brain-find
description: >
  Use this skill when the user wants to find something specific in their Second Brain —
  any search query, lookup, or "where did I write about X?" request. This covers
  searching across vault files, journal entries, concepts, action items, and the
  knowledge graph simultaneously, returning ranked results with graph-adjacent
  connections. Also use when the user wants to locate a note, recall when they
  discussed a topic, or check if they already captured something. Prefer this skill
  for any retrieval request, even vague ones. Distinguished from brain-trace (which
  follows a concept's evolution over time, not a point-in-time search), brain-resources
  (which catalogs the entire knowledge base rather than answering a specific query), and
  simple file reads (this searches across vault, DB, and knowledge graph together).
---

# brain-find — Semantic Search

Search across the entire Second Brain — vault files, SQLite database, and knowledge graph — to find notes, concepts, journal entries, and action items matching a query.

## Steps

### 1. Extract Query

Extract the search query from the user's message. If the query contains multiple words, split into individual keywords for broader matching. Use the full phrase for exact matches and individual keywords for fuzzy coverage.

For example, "where did I write about morning routines" extracts:
- Full phrase: `morning routines`
- Keywords: `morning`, `routines`

### 2. Search Vault Files

Use Grep to search vault files (`vault/**/*.md`) for the query terms. Return file paths, line numbers, and matching lines. Limit to 15 results.

### 3. Search SQLite Database

Run all queries against `data/brain.db` using `sqlite3`. For each query, replace `<query>` with the user's search terms (use `%query%` for LIKE patterns).

a. **Search journal entries:**
```sql
SELECT date, file_path, summary,
       CASE WHEN content LIKE '%<query>%' THEN 'content' ELSE 'summary' END AS match_type
FROM journal_entries
WHERE content LIKE '%<query>%' OR summary LIKE '%<query>%'
ORDER BY date DESC LIMIT 10;
```

b. **Search concepts:**
```sql
SELECT title, file_path, status, summary, mention_count
FROM concept_metadata
WHERE title LIKE '%<query>%' OR summary LIKE '%<query>%'
ORDER BY mention_count DESC LIMIT 10;
```

c. **Search action items:**
```sql
SELECT description, source_file, source_date, status, icor_element
FROM action_items
WHERE description LIKE '%<query>%'
ORDER BY source_date DESC LIMIT 10;
```

d. **Search vault index:**
```sql
SELECT file_path, file_type, title, last_modified
FROM vault_index
WHERE title LIKE '%<query>%' OR file_path LIKE '%<query>%'
ORDER BY last_modified DESC LIMIT 10;
```

### 4. Graph-Adjacent Results

Find files linked to/from matching files using the wikilinks graph. Run against `data/brain.db` using `sqlite3`:

```sql
SELECT vi2.file_path, vi2.title, vi2.file_type
FROM vault_index vi1, json_each(vi1.wikilinks) AS link
JOIN vault_index vi2 ON vi2.title = link.value
WHERE vi1.title LIKE '%<query>%' OR vi1.file_path LIKE '%<query>%'
LIMIT 10;
```

These are "related" results — files that don't directly match but are connected to matching files via wikilinks.

### 5. For Multi-Word Queries

If the full phrase returns few results (<3 total), re-run the SQLite queries with individual keywords to broaden coverage. Deduplicate results by file_path.

### 6. Rank and Present Results

Combine all results and rank by relevance:

1. **Exact title matches** (concept or vault_index title matches query exactly) — highest
2. **Content matches** (journal content or vault file grep hits) — high
3. **Summary matches** (concept or journal summary) — medium
4. **Action item matches** — medium
5. **Graph-adjacent results** (linked from matching files) — lower

Present results grouped by source:

```markdown
## Search Results: "[query]"

### Direct Matches

#### Concepts
| Title | Status | Mentions | File |
|---|---|---|---|
| [title] | [status] | [N] | [file_path] |

#### Journal Entries
| Date | Summary | Match Type | File |
|---|---|---|---|
| [date] | [summary] | [content/summary] | [file_path] |

#### Vault Files
| File | Type | Last Modified | Matching Line |
|---|---|---|---|
| [file_path] | [type] | [date] | [snippet] |

#### Action Items
| Description | Status | Date | ICOR Element |
|---|---|---|---|
| [description] | [status] | [date] | [element] |

---

### Related (Graph-Adjacent)
| File | Title | Type | Connected Via |
|---|---|---|---|
| [file_path] | [title] | [type] | [linking file] |

---

**Total results:** [N] direct + [N] related
```

### 7. Offer Follow-Up

After presenting results, offer to:
- Read the top result in full
- Open a specific file for detailed review
- Narrow the search with additional terms
- Search Notion databases for the same query (using `notion-search`)
