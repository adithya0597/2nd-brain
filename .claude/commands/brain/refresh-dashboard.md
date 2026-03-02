# /brain:refresh-dashboard — Update Cockpit Dashboard

Recalculate all attention scores and update the Notion cockpit dashboard with current system state.

## Steps

### 1. Recalculate Attention Scores
For each Key Element in the ICOR hierarchy:

a. Count mentions in the last 30 days:
```sql
SELECT json_each.value AS element, COUNT(*) AS mention_count,
       COUNT(DISTINCT je.date) AS journal_days
FROM journal_entries je, json_each(je.icor_elements)
WHERE je.date >= date('now', '-30 days')
GROUP BY json_each.value;
```

b. Get max mentions for normalization:
```sql
SELECT MAX(cnt) FROM (
    SELECT COUNT(*) as cnt
    FROM journal_entries, json_each(journal_entries.icor_elements)
    WHERE date >= date('now', '-30 days')
    GROUP BY json_each.value
);
```

c. Calculate normalized score for each element:
`score = (mention_count / max_mentions) * 100`
If max_mentions is 0, all scores are 0.

d. Flag neglected elements (>7 days without mention):
```sql
SELECT h.id, h.name FROM icor_hierarchy h
WHERE h.level = 'key_element'
  AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days'));
```

### 2. Update SQLite
For each Key Element:
```sql
UPDATE icor_hierarchy SET attention_score = <score> WHERE name = '<element>' AND level = 'key_element';
```

Insert new attention_indicators record:
```sql
INSERT INTO attention_indicators (icor_element_id, period_start, period_end, mention_count, journal_days, attention_score, flagged)
VALUES (<id>, date('now', '-30 days'), date('now'), <count>, <days>, <score>, <flagged>);
```

### 3. Gather Dashboard Data

a. **ICOR Overview** — Query full hierarchy with scores:
```sql
SELECT d.name AS dimension, ke.name AS key_element,
       ke.attention_score, ke.last_mentioned
FROM icor_hierarchy d
JOIN icor_hierarchy ke ON ke.parent_id = d.id
WHERE d.level = 'dimension' AND ke.level = 'key_element'
ORDER BY d.id, ke.attention_score DESC;
```

b. **Active Projects** — Use `notion-search` on Projects DB for Status "Doing" or "Ongoing"

c. **Pending Actions** — Count from SQLite:
```sql
SELECT COUNT(*) FROM action_items WHERE status = 'pending';
```

d. **Journal Consistency:**
```sql
SELECT COUNT(DISTINCT date) AS days_journaled
FROM journal_entries WHERE date >= date('now', '-30 days');
```

e. **Recent Concepts:**
```sql
SELECT title, status, mention_count FROM concept_metadata
ORDER BY last_mentioned DESC LIMIT 5;
```

### 4. Create/Update Notion Dashboard
Read `data/notion-registry.json` for the dashboard_page_id.

**If no dashboard exists:**
Create a new page in Notion using `notion-create-pages`:
- Create as a standalone page (no parent, or under the "My assistant" page)
- Title: "Second Brain Cockpit"
- Content should include the dashboard markdown below
- Save the page ID to `data/notion-registry.json` as dashboard_page_id

**If dashboard exists:**
Use `notion-update-page` with command `replace_content` to update the existing page.

**Dashboard Content:**
```markdown
# ICOR Attention Heatmap
*Last updated: [today's date]*

## Health & Vitality
| Key Element | Score | Last Mentioned | Status |
|---|---|---|---|
| Fitness | [score] | [date] | [OK/Neglected] |
| Nutrition | [score] | [date] | [OK/Neglected] |
| Sleep | [score] | [date] | [OK/Neglected] |
| Mental Health | [score] | [date] | [OK/Neglected] |

## Wealth & Finance
[same format for each dimension...]

## [Continue for all 6 dimensions]

---

# Active Projects
| Project | Status | Progress |
|---|---|---|
| [from Notion] | [status] | [progress] |

---

# Pending Actions: [count]

# Journal Consistency: [X]/30 days (last 30 days)

# Recent Concepts
| Concept | Status | Mentions |
|---|---|---|
| [concept] | [seedling/growing/evergreen] | [count] |
```

### 5. Report
Present the dashboard summary to the user and provide the Notion page URL if created/updated.
