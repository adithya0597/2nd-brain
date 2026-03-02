# /brain:today — Morning Review

Start the day with a comprehensive morning briefing and create today's daily note.

## Steps

### 1. Load Context
Perform all steps from `/brain:context-load` internally (read identity files, query SQLite for recent state, pending actions, attention flags).

### 2. Create Today's Daily Note
Check if `vault/Daily Notes/YYYY-MM-DD.md` exists for today's date. If not, create it using the template from `vault/Templates/Daily Note.md`:
- Replace `{{date:YYYY-MM-DD}}` with today's date
- Replace `{{date:dddd, MMMM D, YYYY}}` with the full formatted date

### 3. Gather Yesterday's Unfinished Business
Query SQLite:
```sql
SELECT id, description, source_file, icor_element
FROM action_items
WHERE status = 'pending'
  AND source_date <= date('now', '-1 day')
ORDER BY source_date DESC;
```

### 4. Fetch Active Projects from Notion
Use the Notion MCP tool `notion-search` to search the Projects data source for active projects:
- Search `collection://231fda46-1a19-8171-9b6d-000b3e3409be` for projects with Status "Doing" or "Ongoing"
- For each active project, note its name, status, and any related goal

### 5. Check Attention Indicators
Query SQLite for neglected Key Elements (>7 days without mention):
```sql
SELECT h.name AS key_element, p.name AS dimension,
       h.last_mentioned,
       CASE WHEN h.last_mentioned IS NULL THEN 'Never mentioned'
            ELSE CAST(julianday('now') - julianday(h.last_mentioned) AS INTEGER) || ' days ago'
       END AS last_activity
FROM icor_hierarchy h
JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE h.level = 'key_element'
  AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days'))
ORDER BY h.last_mentioned ASC NULLS FIRST;
```

### 6. Generate Morning Briefing
Compile all information into a morning briefing and append it to today's daily note under the "## Morning Intentions" section. The briefing should include:

**Format:**
```markdown
### Morning Briefing (auto-generated)

**Carried Over Actions:**
- [ ] [action from yesterday]

**Active Projects:**
- [Project Name] — [Status] — [Goal if linked]

**Attention Alerts:**
- [Key Element] ([Dimension]) — [days since last mention]

**Suggested Focus Areas:**
Based on your ICOR priorities and recent patterns, consider focusing on:
1. [Specific suggestion based on neglected areas and pending actions]
2. [Specific suggestion]
3. [Specific suggestion]
```

Present the briefing to the user and confirm it was appended to today's daily note.
