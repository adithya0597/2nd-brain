# /brain:schedule — Weekly Schedule Generator

Generate an energy-aware weekly schedule by combining pending tasks, Notion deadlines, historical energy patterns, and ICOR balance data.

**Usage:** `/brain:schedule [target]` — target can be empty (current week), "next week", or a specific date (uses the week containing that date).

## Pre-Computed Analytics

The Context Data includes these pre-computed analytics — use them directly instead of re-querying:
- **attention_gaps**: ICOR elements ranked by severity (critical/moderate/mild) with days-since-mention. Use for Step 4 (ICOR Dimension Coverage) and to identify "Neglected Recovery" tasks in Step 6.
- **stale_actions**: Pending action items grouped by ICOR element with age and staleness data. Use for Step 3 (Pending Action Items) — these are already filtered and enriched.

## Steps

### 1. Determine Target Week
Parse `$ARGUMENTS`:
- If empty, use the current week (Monday through Sunday containing today)
- If "next" or "next week", use next Monday through Sunday
- If a specific date is given, use the Monday–Sunday week containing that date

Calculate `week_start` (Monday) and `week_end` (Sunday) dates.

### 2. Gather Energy Patterns from Journal History
Query SQLite for historical energy and mood by day of week (last 90 days):
```sql
SELECT
    CASE CAST(strftime('%w', date) AS INTEGER)
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
    END AS day_name,
    CAST(strftime('%w', date) AS INTEGER) AS day_num,
    COUNT(*) AS entries,
    ROUND(AVG(CASE energy WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END), 1) AS avg_energy,
    ROUND(AVG(sentiment_score), 2) AS avg_sentiment,
    ROUND(AVG(CASE mood
        WHEN 'great' THEN 5 WHEN 'good' THEN 4 WHEN 'okay' THEN 3
        WHEN 'low' THEN 2 WHEN 'bad' THEN 1 END), 1) AS avg_mood
FROM journal_entries
WHERE date >= date('now', '-90 days')
GROUP BY day_num
ORDER BY day_num;
```

### 3. Gather Pending Action Items
Query SQLite for all pending actions with ICOR context:
```sql
SELECT ai.id, ai.description, ai.source_date, ai.icor_element, ai.icor_project,
       h.name AS element_name, p.name AS dimension_name,
       CAST(julianday('now') - julianday(ai.source_date) AS INTEGER) AS age_days
FROM action_items ai
LEFT JOIN icor_hierarchy h ON ai.icor_element = h.name
LEFT JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE ai.status = 'pending'
ORDER BY ai.source_date ASC;
```

### 4. Check ICOR Dimension Coverage
Query SQLite for neglected areas needing recovery attention:
```sql
SELECT p.name AS dimension,
       COUNT(DISTINCT ai.id) AS pending_actions,
       COUNT(DISTINCT CASE WHEN ai.source_date >= date('now', '-7 days') THEN ai.id END) AS recent_actions,
       MAX(h.attention_score) AS max_attention,
       MIN(COALESCE(h.last_mentioned, '2000-01-01')) AS oldest_mention
FROM icor_hierarchy p
LEFT JOIN icor_hierarchy h ON h.parent_id = p.id AND h.level = 'key_element'
LEFT JOIN action_items ai ON ai.icor_element = h.name AND ai.status = 'pending'
WHERE p.level = 'dimension'
GROUP BY p.name
ORDER BY pending_actions DESC;
```

### 5. Fetch Active Tasks and Projects from Notion
Use the tasks and projects from the Notion data in the Context Data section:

**Active Tasks:**
From the Context Data, identify tasks with Status "To Do" or "Doing". Note each task's name, status, due date, priority, energy level, and linked project.

**Active Projects:**
From the Context Data, identify projects with Status "Doing". Note each project's name, target deadline, and linked goal.

**Active Goals:**
From the Context Data, identify goals with Status "Active". Note each goal's name and target deadline.

### 6. Categorize All Tasks
Group all gathered tasks, action items, and Notion items into these categories:

- **Critical Path**: Has a deadline within the target week, or blocks other work. Assign highest scheduling priority.
- **High Energy**: Deep work requiring focus — coding, writing, strategic thinking, creative tasks. Match to high-energy days.
- **Low Energy**: Administrative tasks, email, routine reviews, data entry. Match to low-energy periods.
- **Neglected Recovery**: Tasks that address ICOR dimensions with low attention scores or no recent mentions. Distribute across the week.
- **Maintenance**: Ongoing habits, reviews, health routines, recurring tasks. Place consistently across days.

Use the task's Energy property from Notion (High/Low) when available. For SQLite action items without an energy tag, infer from the task description (writing/coding/planning = High Energy; admin/review/email = Low Energy).

### 7. Allocate Tasks to Days
Using the energy forecast from Step 2, distribute tasks across the target week:

- Place **Critical Path** items on their deadline day or one day before
- Place **High Energy** tasks on days with historically high energy scores (avg_energy >= 2.5)
- Place **Low Energy** tasks on days with historically lower energy (avg_energy < 2.0, typically Friday afternoons)
- Distribute **Neglected Recovery** tasks evenly across the week, one per day
- Place **Maintenance** items at consistent times (morning or evening slots)
- Flag any day that exceeds 8 tasks as over-committed

### 8. Generate Weekly Plan

Present the schedule in this format:

```markdown
## Weekly Schedule — [Mon Date] to [Sun Date]

### Week Overview
- **Total tasks:** [N]
- **Critical deadlines:** [N]
- **ICOR balance:** [assessment of dimensional coverage]
- **Over-commitment warning:** [if >8 tasks/day on any day, flag it here]

### Energy Forecast
Based on your journal history (last 90 days), your typical energy pattern:
| Day | Historical Energy | Mood Trend | Best For |
|---|---|---|---|
| Monday | [High/Med/Low] | [avg_mood] | [recommendation] |
| Tuesday | ... | ... | ... |
| Wednesday | ... | ... | ... |
| Thursday | ... | ... | ... |
| Friday | ... | ... | ... |
| Saturday | ... | ... | ... |
| Sunday | ... | ... | ... |

### Daily Breakdown

#### Monday [Date]
**Focus Theme:** [Primary ICOR dimension for the day]
- [ ] [Critical] [Task description] — Due today
- [ ] [High Energy] [Task description] — [Project/Goal context]
- [ ] [Maintenance] [Routine task]
- [ ] [Neglected Recovery] [Task addressing neglected dimension]

#### Tuesday [Date]
**Focus Theme:** [Primary ICOR dimension]
- [ ] ...

#### Wednesday [Date]
...

#### Thursday [Date]
...

#### Friday [Date]
...

#### Saturday [Date]
...

#### Sunday [Date]
...

### Weekly Balance Check
| Dimension | Tasks This Week | Status |
|---|---|---|
| Health & Vitality | [N] | [Covered/Neglected] |
| Wealth & Finance | [N] | [Covered/Neglected] |
| Relationships | [N] | [Covered/Neglected] |
| Mind & Growth | [N] | [Covered/Neglected] |
| Purpose & Impact | [N] | [Covered/Neglected] |
| Systems & Environment | [N] | [Covered/Neglected] |

### Recommendations
1. [Suggestion based on energy patterns and task distribution]
2. [Suggestion for addressing neglected ICOR dimensions]
3. [Over-commitment adjustment if any day exceeds capacity]
```

### 9. 30-Day Trends

If trend data is available in the Context Data (mood_energy_30d, engagement_trend_30d):

Use the 30-day mood, energy, and engagement trends to inform scheduling decisions. If certain days consistently show low energy, schedule lighter tasks on those days. If engagement has been declining over the past weeks, suggest building in more variety or reducing over-commitment. Include a brief "Trend Insights" note in the Weekly Overview section.

### 10. Save Options
Offer the user these options:
- **Append to daily notes:** Add each day's task list to the corresponding `vault/Daily Notes/YYYY-MM-DD.md` file under a "## Scheduled Tasks" section
- **Save as weekly plan:** Save the full schedule to `vault/Projects/Weekly-Plan-YYYY-MM-DD.md` (using the Monday date)
- **Create Notion tasks:** For any SQLite action items not already in Notion (no `external_id`), offer to create them as Notion tasks in `collection://231fda46-1a19-8125-95f4-000ba3e22ea6` with appropriate Status, Priority, and Due dates
