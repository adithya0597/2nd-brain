# /brain:today — Morning Review

Start the day with a comprehensive morning briefing and create today's daily note.

## Pre-Computed Analytics

The Context Data includes these pre-computed analytics — use them directly instead of re-querying:
- **top3_morning**: The 3 highest-priority items for today, scored by age, project linkage, and ICOR importance. Use these as the core of "Suggested Focus Areas."
- **stuck_item**: The single most stale action item. Highlight this prominently in the briefing as needing attention.
- **attention_gaps**: ICOR elements with severity ratings (critical/moderate/mild). Use for "Attention Alerts" instead of the raw neglected-elements SQL.

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
Review the active projects from the Notion data in the Context Data section below:
- Identify projects with Status "Doing" or "Ongoing"
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

### 7. Cross-Session Trends

If mood/energy trend data is available in the Context Data (mood_energy_7d, engagement_trend_7d):

Compare today's mood and energy with the 7-day trend. Note if the user's engagement has been rising or declining. If there's a notable pattern (e.g., consistently low energy on certain days, or a multi-day mood dip), mention it briefly in the briefing under a "Trends" subsection.

Present the briefing to the user and confirm it was appended to today's daily note.
