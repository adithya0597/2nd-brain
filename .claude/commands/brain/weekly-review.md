# /brain:weekly-review — GTD Weekly Review

Perform a comprehensive weekly review: audit open loops, review completed work, check ICOR balance, and set priorities for the coming week.

## Steps

### 1. Review Last 7 Days of Journal Entries
From the Context Data, review all journal entries from the past week. For each day, note:
- Mood and energy trends
- Key themes and ICOR elements touched
- Whether the day had a morning plan and evening review

Summarize the week's trajectory: was it focused, scattered, energized, or drained?

### 2. Audit All Pending Action Items
From the Context Data, review every pending action item. For each one, recommend one of:
- **Keep** — still relevant, carry forward to next week
- **Complete** — can be closed now (already done or no longer needed)
- **Defer** — not urgent, move to Someday/Maybe
- **Delete** — no longer relevant, remove

Group recommendations by ICOR dimension. Flag any action items older than 14 days as stale.

### 3. Check ICOR Dimension Balance
From the Context Data, review attention indicators across all six dimensions:
- Health & Vitality
- Wealth & Finance
- Relationships
- Mind & Growth
- Purpose & Impact
- Systems & Environment

For each dimension, assess:
- How many journal entries touched it this week
- How many pending actions belong to it
- Whether attention is rising, falling, or stable
- Flag any dimension with zero touches as "neglected"

### 4. Review Active Projects
From the Notion data in the Context Data, review all active projects (Status: Doing or Ongoing):
- Note progress made this week (actions completed, journal mentions)
- Flag any project with no activity in the past 7 days
- Check if any project deadlines are approaching (within 14 days)

### 5. Identify Next Week's Top 3 Priorities
Based on all the above, recommend the user's top 3 priorities for the coming week. Each priority should:
- Address a specific gap, neglected dimension, or stalled project
- Be concrete and actionable (not vague like "focus more on health")
- Reference a specific action item, project, or ICOR element

### 6. Generate Weekly Review Summary

**Format:**
```markdown
## Weekly Review — [date range]

### Week in Review
[2-3 sentence summary of the week's trajectory]

**Days journaled:** [X/7]
**Mood trend:** [improving/stable/declining]
**Energy trend:** [improving/stable/declining]

### Action Item Audit
**Total pending:** [count]
- Keep: [count] items
- Complete: [count] items
- Defer: [count] items
- Delete: [count] items
- Stale (>14 days): [count] items

[List each action with its recommendation]

### ICOR Balance
| Dimension | Touches | Actions | Trend | Status |
|---|---|---|---|---|
| [dimension] | [count] | [count] | [trend] | [OK/Neglected/Overloaded] |

### Project Status
[List each active project with weekly progress notes]

### Top 3 Priorities for Next Week
1. [Priority with rationale]
2. [Priority with rationale]
3. [Priority with rationale]

### Open Loops
[Any unresolved items, waiting-fors, or decisions needed]
```

Present the complete review to the user.
