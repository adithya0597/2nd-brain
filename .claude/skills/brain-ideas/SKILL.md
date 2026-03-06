---
name: brain-ideas
description: >
  Use this skill when the user wants to mine their own notes, journal, or knowledge
  base for actionable ideas — any request for personalized creative suggestions,
  "what should I work on next?", or discovering opportunities hidden in their data.
  This includes finding underexplored concept connections, identifying knowledge gaps
  worth filling, surfacing neglected relationships, and turning journal patterns into
  concrete next steps across five categories: tools to build, people to reach out to,
  topics to investigate, content to create, and quick experiments. Distinguished from
  generic brainstorming (this skill mines YOUR vault data, not general ideas) and from
  brain-emerge (which surfaces unnamed patterns rather than actionable ideas).
---

# brain-ideas — Actionable Idea Generation

Generate specific, actionable ideas from journal patterns, concept growth, neglected relationships, and attention gaps across the Second Brain.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Gather Raw Signals

Run against `data/brain.db` using `sqlite3`:

a. Recent journal entries (last 60 days):
```sql
SELECT date, content, icor_elements, summary, sentiment_score, mood, energy
FROM journal_entries
WHERE date >= date('now', '-60 days')
ORDER BY date DESC;
```

b. Seedling and growing concepts:
```sql
SELECT title, status, mention_count, last_mentioned,
       first_mentioned, icor_elements, summary
FROM concept_metadata
WHERE status IN ('seedling', 'growing')
ORDER BY last_mentioned DESC;
```

c. Stale pending actions (older than 14 days — likely blocked or unclear):
```sql
SELECT description, source_file, source_date, icor_element, icor_project
FROM action_items
WHERE status = 'pending'
  AND source_date <= date('now', '-14 days')
ORDER BY source_date ASC;
```

d. Recurring themes and attention gaps:
```sql
-- Recurring themes (3+ mentions in 60 days)
WITH element_freq AS (
    SELECT json_each.value AS element,
           COUNT(*) AS freq,
           MIN(date) AS first_seen,
           MAX(date) AS last_seen
    FROM journal_entries, json_each(journal_entries.icor_elements)
    WHERE date >= date('now', '-60 days')
    GROUP BY json_each.value
)
SELECT element, freq, first_seen, last_seen,
       CAST(julianday(last_seen) - julianday(first_seen) AS INTEGER) AS span_days
FROM element_freq
WHERE freq >= 3
ORDER BY freq DESC;

-- ICOR attention gaps
SELECT h.name AS element, p.name AS dimension,
       h.attention_score,
       COALESCE(ai.mention_count, 0) AS recent_mentions,
       CASE WHEN h.attention_score > 0 AND COALESCE(ai.mention_count, 0) = 0
            THEN 'high_gap'
            WHEN h.attention_score > COALESCE(ai.attention_score, 0) * 2
            THEN 'moderate_gap'
            ELSE 'aligned'
       END AS gap_status
FROM icor_hierarchy h
JOIN icor_hierarchy p ON h.parent_id = p.id
LEFT JOIN attention_indicators ai ON ai.icor_element_id = h.id
  AND ai.period_end = (SELECT MAX(period_end) FROM attention_indicators)
WHERE h.level = 'key_element'
ORDER BY gap_status, h.attention_score DESC;
```

### 3. Fetch Notion Data

Use Notion MCP tools to pull active entities:

a. **Active Projects** — Search `collection://231fda46-1a19-8171-9b6d-000b3e3409be` for projects with Status "Doing" or "Ongoing". Note their names, goals, and tags.

b. **Active Goals** — Search `collection://231fda46-1a19-810f-b0ac-000bbab78a4a` for goals with Status "Active". Note their names, tags, and linked projects.

c. **People with recent interactions** — Search `collection://231fda46-1a19-811c-ac4d-000b87d02a66` for all people. Identify those with stale "Last Check-In" dates (>30 days) or no recent mentions in journal entries.

d. **Recent Notes** — Search `collection://231fda46-1a19-8139-a401-000b477c8cd0` for notes created in the last 30 days. Look for types: Idea, Voice Note, Web Clip — these are raw inputs that may not have been processed.

### 4. Analyze Across Five Categories

For each category, generate 2-5 specific ideas by cross-referencing the gathered data:

**Tools to Build**
- Look for pain points: recurring complaints, manual processes described in journals, "I wish I could..." phrases
- Look for stale actions that could be automated
- Look for patterns where the same workflow appears across multiple projects
- Cross-reference with active projects to see what's missing

**People to Reach Out To**
- People DB entries with Last Check-In > 30 days ago
- Names mentioned in recent journal entries but not in the People DB
- People linked to active projects or goals who haven't been contacted recently
- Colleagues/mentors relevant to growing concepts or attention gaps

**Topics to Investigate**
- Seedling concepts with 3+ mentions (signal of genuine interest)
- Recurring questions that appear in journal entries
- Attention gaps — areas the user declared important but hasn't explored
- Growing concepts that could benefit from deeper research

**Content to Create**
- Evergreen or growing concepts with enough substance to share
- Topics where journal entries show the user has developed a unique perspective
- Patterns from emerge-style analysis that could become blog posts, threads, or talks
- Meeting notes or project learnings worth synthesizing into shareable form

**Quick Experiments**
- Low-effort tests inspired by seedling concepts (try for 1 week)
- Small habit changes suggested by drift analysis
- Tool trials related to active project needs
- Outreach experiments (one message, one ask) tied to People DB

### 5. Score Each Idea

Rate every idea on four dimensions (1-5 scale):

| Dimension | Meaning |
|---|---|
| **Evidence** | How many independent data points support this idea? (1 = hunch, 5 = 5+ sources) |
| **ICOR Alignment** | Does it serve an active Goal or high-attention Key Element? (1 = tangential, 5 = core goal) |
| **Freshness** | Is the signal recent and active? (1 = 60+ days old, 5 = last 7 days) |
| **Feasibility** | Can it be started this week? (1 = major project, 5 = 30-minute action) |

Compute a composite score: `(Evidence * 2 + ICOR Alignment * 2 + Freshness + Feasibility) / 6`

Mark the top idea in each category with a star.

### 6. Generate Idea Report

Use the output template in `references/output-template.md` to format the report.

### 7. Output

Present the idea report to the user. Offer to:
- Save as `vault/Concepts/Idea-Report-YYYY-MM-DD.md`
- Create Notion tasks for top-scored ideas (using Tasks collection `collection://231fda46-1a19-8125-95f4-000ba3e22ea6`)
- Add specific people outreach as action items in today's daily note
