---
name: brain-today
description: >
  Use this skill when the user wants to kick off their day or get a morning
  briefing — any request that signals "I'm starting my day and want situational
  awareness." This includes waking up and wanting to know what to tackle,
  launching a morning routine, asking what's on the agenda, or requesting a
  daily digest. Creates today's daily note, surfaces yesterday's unfinished
  actions, checks active Notion projects, and synthesizes a personalized focus
  briefing. Distinguished from general context-loading (which doesn't create a
  daily note or morning briefing), from weekly scheduling (which plans an
  entire week, not just today), and from historical journal lookups (which are
  about the past, not today's forward-looking orientation).
---

# Morning Review

Start the day with a comprehensive morning briefing and create today's daily note.

## Steps

### 1. Resolve Today's Date
Run `date +%Y-%m-%d` to get today's date. Also resolve the full formatted date with `date '+%A, %B %-d, %Y'`.

### 2. Load Context
Perform all steps from the `brain-context-load` skill internally (read identity files, query SQLite for recent state, pending actions, attention flags).

### 3. Create Today's Daily Note
Check if `vault/Daily Notes/YYYY-MM-DD.md` exists for today's date. If not, create it using the template from `vault/Templates/Daily Note.md`:
- Replace `{{date:YYYY-MM-DD}}` with today's date
- Replace `{{date:dddd, MMMM D, YYYY}}` with the full formatted date

### 4. Gather Yesterday's Unfinished Business
Run against `data/brain.db` using `sqlite3`:
```sql
SELECT id, description, source_file, icor_element
FROM action_items
WHERE status = 'pending'
  AND source_date <= date('now', '-1 day')
ORDER BY source_date DESC;
```

### 5. Fetch Active Projects from Notion
Use the Notion MCP tool `notion-search` to search the Projects data source for active projects:
- Search `collection://231fda46-1a19-8171-9b6d-000b3e3409be` for projects with Status "Doing" or "Ongoing"
- For each active project, note its name, status, and any related goal

### 6. Check Attention Indicators
Run against `data/brain.db` using `sqlite3` for neglected Key Elements (>7 days without mention):
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

### 7. Generate Morning Briefing
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
