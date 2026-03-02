# /brain:close-day — Evening Review

Close out the day by parsing today's journal, extracting actions, indexing entries, and updating attention indicators.

## Steps

### 1. Read Today's Daily Note
Read `vault/Daily Notes/YYYY-MM-DD.md` for today's date. If it doesn't exist, inform the user and exit.

### 2. Extract and Parse Content
Analyze the daily note content to identify:

**Action Items** — Look for:
- Lines starting with `- [ ]` (unchecked checkboxes)
- Phrases containing: "TODO", "todo", "need to", "remind me", "should", "must", "have to", "follow up", "action:"
- Imperative sentences that imply tasks

**Mood & Energy** — Check frontmatter for mood and energy values.

**ICOR Elements** — For each log entry or reflection:
- Match against Key Element names from `vault/Identity/ICOR.md`
- Read ICOR.md to get the full list of Key Elements
- Tag entries with matching elements (e.g., mention of "gym" -> Fitness, "portfolio" -> Investments)

### 3. Insert Journal Entry into SQLite
For the overall daily note content, run:
```sql
INSERT INTO journal_entries (date, content, mood, energy, icor_elements, summary, file_path)
VALUES ('<today>', '<full content>', '<mood>', '<energy>', '<json array of matched elements>', '<AI-generated 2-3 sentence summary>', 'vault/Daily Notes/YYYY-MM-DD.md');
```

### 4. Insert Action Items into SQLite
For each extracted action:
```sql
INSERT INTO action_items (description, source_file, source_date, status, icor_element, icor_project)
VALUES ('<action text>', 'vault/Daily Notes/YYYY-MM-DD.md', '<today>', 'pending', '<matched ICOR element>', '<matched project if any>');
```

### 5. Update Attention Indicators
For each ICOR Key Element mentioned today, update the icor_hierarchy table:
```sql
UPDATE icor_hierarchy SET last_mentioned = '<today>', attention_score = attention_score + 1 WHERE name = '<element_name>' AND level = 'key_element';
```

### 6. Identify Concept Graduation Candidates
Query for themes appearing 3+ times in the last 14 days:
```sql
SELECT je.icor_elements, COUNT(*) as mentions
FROM journal_entries je
WHERE je.date >= date('now', '-14 days')
GROUP BY je.icor_elements
HAVING mentions >= 3;
```
If candidates found, mention them and suggest running `/brain:graduate`.

### 7. Offer to Push Actions to Notion
Ask the user if they want to push pending actions to the Notion Tasks DB. If yes, for each action use the Notion MCP tool `notion-create-pages` with:
- Parent: `collection://231fda46-1a19-8125-95f4-000ba3e22ea6` (Tasks data source)
- Properties: Name (action description), Status: "To Do"
- After creation, update the action_items row with the external_id and external_system='notion_tasks'

### 8. Append Evening Summary
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
