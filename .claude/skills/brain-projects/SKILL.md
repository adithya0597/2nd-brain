---
name: brain-projects
description: >
  Use this skill when the user wants to see the status of their active projects,
  understand what's blocked or overdue, or get a cross-dimensional view of how
  their work maps to life goals. This covers any request about project health,
  task completion rates, deadline tracking, stale projects, or which ICOR dimensions
  have too many or too few active projects. Also use when the user asks "how are my
  projects going?" or wants to prioritize across competing workstreams. Distinguished
  from brain-schedule (which plans the upcoming week) and brain-today (which gives a
  morning briefing focused on today's priorities, not deep project analysis).
---

# brain-projects — Active Project Dashboard

Generate a cross-dimensional project dashboard showing active projects, task completion, blockers, and ICOR dimension coverage.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Gather SQLite Data

Run against `data/brain.db` using `sqlite3`:

a. Pending actions grouped by project:
```sql
SELECT icor_project, COUNT(*) AS action_count,
       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed
FROM action_items
WHERE icor_project IS NOT NULL AND icor_project != ''
GROUP BY icor_project
ORDER BY pending DESC;
```

b. Dimension-to-project mapping:
```sql
SELECT p.name AS dimension, h.name AS key_element,
       ai.icor_project AS project,
       COUNT(ai.id) AS action_count
FROM action_items ai
JOIN icor_hierarchy h ON ai.icor_element = h.name
JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE ai.icor_project IS NOT NULL AND ai.icor_project != ''
  AND p.level = 'dimension'
GROUP BY p.name, h.name, ai.icor_project
ORDER BY p.name, action_count DESC;
```

c. Stale project actions (no activity in 14+ days):
```sql
SELECT description, icor_project, icor_element, source_date,
       CAST(julianday('now') - julianday(source_date) AS INTEGER) AS age_days
FROM action_items
WHERE status = 'pending' AND icor_project IS NOT NULL
  AND source_date <= date('now', '-14 days')
ORDER BY age_days DESC;
```

### 3. Fetch Notion Data

a. **Active Projects** — Query `collection://231fda46-1a19-8171-9b6d-000b3e3409be` for projects with Status in ("Doing", "Planned", "Ongoing"). Retrieve: Name, Status, Tag, Goal, Target Deadline, and linked Tasks count.

b. **Related Tasks** — Query `collection://231fda46-1a19-8125-95f4-000ba3e22ea6` for tasks with Status "To Do" or "Doing" that have a Project relation set. Group by project.

c. **Active Goals** — Query `collection://231fda46-1a19-810f-b0ac-000bbab78a4a` for goals with Status "Active". Note linked Projects.

d. **Tags (Dimensions)** — Query `collection://231fda46-1a19-8195-8338-000b82b65137` for Tags with Type "Area". Map projects to their ICOR dimensions via the Tag relation.

### 4. Analyze

For each project, compute:
- **Task completion rate**: done / (done + pending) tasks
- **Blocked items**: pending tasks with age > 14 days
- **Cross-dimensional coverage**: which ICOR dimensions does this project touch?
- **Goal alignment**: is the project linked to an active goal?
- **Deadline proximity**: days until Target Deadline (if set)

Across all projects:
- **Dimension gap analysis**: which dimensions have no active projects?
- **Overloaded dimensions**: which have 3+ active projects?
- **Stale projects**: active status but no task activity in 14+ days

### 5. Generate Dashboard

```markdown
## Project Dashboard — [Date]

**Active projects:** [N] | **Tasks pending:** [N] | **Blocked items:** [N]

---

### Projects by Status

#### Doing
| Project | Goal | Dimension | Tasks (Done/Total) | Blocked | Deadline |
|---|---|---|---|---|---|
| [Name] | [Goal or "—"] | [Dimension] | [N/N] | [N] | [Date or "—"] |

#### Planned
| Project | Goal | Dimension | Tasks Defined | Target Start |
|---|---|---|---|---|
| [Name] | [Goal or "—"] | [Dimension] | [N] | [Date or "—"] |

#### Ongoing (Habits/Routines)
| Project | Dimension | Recent Activity | Consistency |
|---|---|---|---|
| [Name] | [Dimension] | [Last action date] | [Active/Stale] |

---

### Cross-Dimensional View

| Dimension | Active Projects | Tasks Pending | Attention Score | Status |
|---|---|---|---|---|
| Health & Vitality | [N] | [N] | [X.X] | [Balanced/Overloaded/Gap] |
| ... | ... | ... | ... | ... |

---

### Blocked & Overdue

| Item | Project | Age (days) | Dimension |
|---|---|---|---|
| [Description] | [Project] | [N] | [Dimension] |

---

### Suggested Actions

1. [Specific recommendation based on analysis]
2. [Another recommendation]
3. [...]

---

**Top Priority:** [Most urgent project + why]
```

### 6. Output

Present the project dashboard. Offer to:
- Save as `vault/Projects/Dashboard-YYYY-MM-DD.md`
- Create Notion tasks for suggested actions
- Update project status in Notion for stale projects
