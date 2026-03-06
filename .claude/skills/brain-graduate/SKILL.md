---
name: brain-graduate
description: >
  Use this skill when the user wants to promote recurring journal themes into
  formal concept notes — any request about graduating ideas, turning journal
  patterns into standalone knowledge, formalizing emerging thinking, or asking
  "what themes keep coming up?" This covers scanning recent daily notes for
  topics mentioned across multiple days, creating new concept files with
  synthesis and backlinks, and building the vault's evergreen knowledge layer
  from raw journaling. Distinguished from brain-emerge (which surfaces patterns
  for awareness but does not create concept notes) and brain-trace (which
  follows an existing concept's evolution rather than creating new ones from
  journal themes).
---

# brain-graduate -- Concept Graduation

Scan recent journal entries to identify recurring themes and graduate them into standalone concept notes.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Gather Recent Journal Data

Run against `data/brain.db` using `sqlite3`:
```sql
SELECT date, content, icor_elements, summary
FROM journal_entries
WHERE date >= date('now', '-14 days')
ORDER BY date DESC;
```

If no entries found, also scan vault files directly:
Use Glob to find `vault/Daily Notes/*.md` files from the last 14 days, then Read each one.

### 3. Identify Recurring Themes

Analyze all gathered content to find:
- Topics mentioned 3+ times across different days
- Clusters of related ideas that aren't yet formalized
- Emerging patterns in the user's thinking
- Recurring questions or unresolved tensions

Exclude themes that already have concept notes (check `vault/Concepts/` for existing files).

### 4. Present Candidates to User

For each candidate theme, present:
- **Theme Name:** A suggested concept title
- **Mention Count:** How many times it appeared
- **Source Dates:** Which daily notes reference it
- **Key Quotes:** 2-3 representative excerpts
- **Suggested ICOR Element:** Which Key Element it maps to

Ask the user which themes they want to graduate. They can approve, rename, or skip each one.

### 5. Create Concept Notes

For each approved theme:

a. Read the template from `vault/Templates/Concept.md`

b. Create the concept file at `vault/Concepts/{Concept-Name}.md`:
   - Replace `{{title}}` with the concept name
   - Replace `{{date:YYYY-MM-DD}}` with today's date
   - Set `status: seedling` in frontmatter
   - Set `icor_elements` to matched Key Elements
   - Fill "Core Idea" with a synthesis of the recurring theme
   - Fill "Evidence & Examples" with quotes from source journal entries
   - Fill "Connections" with links to related concepts (if any exist in vault/Concepts/)

c. Insert into SQLite. Run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO concept_metadata (title, file_path, status, icor_elements, first_mentioned, last_mentioned, mention_count, summary)
VALUES ('<title>', 'vault/Concepts/<Concept-Name>.md', 'seedling', '<json elements>', '<earliest date>', '<latest date>', <count>, '<synthesis summary>');
```

### 6. Add Backlinks

For each source daily note that mentioned the graduated concept, append a backlink:
```markdown
> Graduated to concept: [[Concept-Name]]
```
Use the Edit tool to append this to the relevant daily notes.

### 7. Report

Summarize what was graduated:
- Number of concepts created
- Files created and their locations
- Suggestion to revisit these seedlings in a week to promote to "growing"
