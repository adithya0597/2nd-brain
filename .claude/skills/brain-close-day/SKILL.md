---
name: brain-close-day
description: >
  Use this skill when the user wants to wrap up their day, do an evening
  review, or process what happened today — any request that signals "my day is
  ending and I want to capture what happened." This includes closing out the
  day, reflecting on today's work, extracting action items from journal
  entries, reviewing what got done, or triggering an end-of-day ritual. Parses
  today's daily note, extracts action items, indexes entries into SQLite,
  updates ICOR attention indicators, identifies concept graduation candidates,
  and optionally pushes actions to Notion. Distinguished from the morning
  review (which is forward-looking orientation, not backward-looking capture)
  and from concept graduation (which promotes recurring themes into standalone
  concept notes rather than closing the day).
---

# Evening Review

Close out the day by parsing today's journal, extracting actions, indexing entries, and updating attention indicators.

## Steps

### 1. Resolve Today's Date
Run `date +%Y-%m-%d` to get today's date.

### 2. Read Today's Daily Note
Read `vault/Daily Notes/YYYY-MM-DD.md` for today's date. If it doesn't exist, inform the user and exit.

### 3. Extract and Parse Content
Analyze the daily note content to identify:

**Action Items** — Look for:
- Lines starting with `- [ ]` (unchecked checkboxes)
- Phrases containing: "TODO", "todo", "need to", "remind me", "should", "must", "have to", "follow up", "action:"
- Imperative sentences that imply tasks

**Mood & Energy** — Check frontmatter for mood and energy values.

**ICOR Elements** — For each log entry or reflection:
- Match against Key Element names from `vault/Identity/ICOR.md`
- Read `vault/Identity/ICOR.md` to get the full list of Key Elements
- Tag entries with matching elements (e.g., mention of "gym" -> Fitness, "portfolio" -> Investments)

### 4. Insert Journal Entry into SQLite
Run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO journal_entries (date, content, mood, energy, icor_elements, summary, file_path)
VALUES ('<today>', '<full content>', '<mood>', '<energy>', '<json array of matched elements>', '<AI-generated 2-3 sentence summary>', 'vault/Daily Notes/YYYY-MM-DD.md');
```

### 5. Insert Action Items into SQLite
For each extracted action, run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO action_items (description, source_file, source_date, status, icor_element, icor_project)
VALUES ('<action text>', 'vault/Daily Notes/YYYY-MM-DD.md', '<today>', 'pending', '<matched ICOR element>', '<matched project if any>');
```

### 6. Update Attention Indicators
For each ICOR Key Element mentioned today, run against `data/brain.db` using `sqlite3`:
```sql
UPDATE icor_hierarchy SET last_mentioned = '<today>', attention_score = attention_score + 1 WHERE name = '<element_name>' AND level = 'key_element';
```

### 7. Identify Concept Graduation Candidates
Run against `data/brain.db` using `sqlite3` for themes appearing 3+ times in the last 14 days:
```sql
SELECT je.icor_elements, COUNT(*) as mentions
FROM journal_entries je
WHERE je.date >= date('now', '-14 days')
GROUP BY je.icor_elements
HAVING mentions >= 3;
```
If candidates found, mention them and suggest running the `brain-graduate` skill.

### 8. Offer to Push Actions to Notion
Ask the user if they want to push pending actions to the Notion Tasks DB. If yes, for each action use the Notion MCP tool `notion-create-pages` with:
- Parent: `collection://231fda46-1a19-8125-95f4-000ba3e22ea6` (Tasks data source)
- Properties: Name (action description), Status: "To Do"
- After creation, update the action_items row with the external_id and external_system='notion_tasks'

### 9. Append Evening Summary
Append to today's daily note:
```markdown

---
### Evening Summary (auto-generated)

**Entries Indexed:** [count] journal entries
**Actions Extracted:** [count] new action items
**ICOR Elements Touched:** [list of elements]
**Concept Candidates:** [list if any, or "None"]
**Notion Sync:** [Pushed X actions / Skipped]
```

Present the summary to the user.
