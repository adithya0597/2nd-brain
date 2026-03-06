---
name: brain-drift
description: >
  Use this skill when the user wants to understand whether their actual behavior
  matches their stated priorities — any request about goal alignment, life audit,
  intention-vs-reality checks, or "am I on track?" This covers checking if
  journaling focus matches ICOR goals, detecting neglected life dimensions,
  questioning whether daily actions reflect stated values, or reviewing balance
  across life areas. Distinguished from brain-emerge (which discovers unnamed
  patterns without comparing against goals) and brain-trace (which follows a
  single concept over time rather than assessing overall alignment).
---

# brain-drift -- Alignment Analysis

Compare stated life priorities (ICOR goals) against actual journaling behavior to identify drift -- the gap between intentions and actions.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Load Stated Priorities

Read `vault/Identity/ICOR.md` to understand the user's declared life architecture:
- Which Dimensions they've defined
- Which Key Elements are prioritized
- Which Goals are listed as active
- Which Projects are currently in progress

### 3. Gather Behavioral Data

Run against `data/brain.db` using `sqlite3`:

Query 30-60 days of journal entries:
```sql
SELECT date, icor_elements, mood, energy, sentiment_score
FROM journal_entries
WHERE date >= date('now', '-60 days')
ORDER BY date;
```

Get attention scores for all Key Elements:
```sql
SELECT h.name AS key_element, p.name AS dimension,
       h.attention_score, h.last_mentioned,
       CASE WHEN h.last_mentioned IS NULL THEN 999
            ELSE CAST(julianday('now') - julianday(h.last_mentioned) AS INTEGER)
       END AS days_since_mention
FROM icor_hierarchy h
JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE h.level = 'key_element'
ORDER BY p.id, h.id;
```

### 4. Calculate Distribution

Analyze the `icor_elements` JSON arrays across all journal entries to compute:
- **Mention count per Key Element** over the analysis period
- **Mention count per Dimension** (aggregate of child Key Elements)
- **Percentage distribution** -- what % of journal focus went to each Dimension
- **Days active** -- how many unique days each element was mentioned

Run against `data/brain.db` using `sqlite3`:
```sql
SELECT json_each.value AS element, COUNT(*) AS mentions,
       COUNT(DISTINCT date) AS active_days
FROM journal_entries, json_each(journal_entries.icor_elements)
WHERE date >= date('now', '-60 days')
GROUP BY json_each.value
ORDER BY mentions DESC;
```

### 5. Compare Intentions vs Behavior

For each ICOR Dimension, calculate:
- **Stated priority:** Based on number of active Goals and Projects
- **Actual focus:** Based on journal mention percentage
- **Drift score:** Gap between stated and actual (positive = over-indexed, negative = neglected)

### 6. Generate Drift Report

```markdown
## Drift Report -- [Date Range]

### Overall Alignment Score: [X/100]

### Dimension Breakdown

| Dimension | Stated Priority | Actual Focus | Drift | Status |
|---|---|---|---|---|
| Health & Vitality | [High/Med/Low] | [X%] | [+/-N] | [Aligned/Over-indexed/Neglected] |
| Wealth & Finance | ... | ... | ... | ... |
| ... | ... | ... | ... | ... |

### Most Neglected Areas
1. **[Key Element]** ([Dimension]) -- [X days since last mention]
   - You have [N] active goals/projects here but [0%] journal focus
   - Suggestion: [specific actionable suggestion]

2. **[Key Element]** ([Dimension]) -- ...

### Over-Indexed Areas
1. **[Key Element]** ([Dimension]) -- [X% of all journal focus]
   - This may indicate productive flow OR avoidance of harder priorities

### Behavioral Patterns
- **Most consistent area:** [Element] -- mentioned on [X] of [Y] days
- **Most volatile area:** [Element] -- sporadic mentions suggest unclear commitment
- **Emerging interest:** [Element] -- increasing mentions over the period

### Recommended Adjustments
1. [Specific suggestion to address the biggest drift]
2. [Specific suggestion]
3. [Specific suggestion]

### Reflection Questions
- Why might you be avoiding [neglected area]?
- Is the over-focus on [area] intentional or habitual?
- What would a more balanced week look like for you?
```

### 7. Output

Present the drift report to the user. Offer to append it to today's daily note or save as a standalone analysis file.
