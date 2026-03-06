---
name: brain-emerge
description: >
  Use this skill when the user wants to discover hidden patterns, implicit
  themes, or unnamed directions lurking across their notes — any request about
  "what patterns do you see," surfacing unconscious priorities, finding recurring
  questions, or synthesizing scattered observations into coherent insights. This
  includes detecting sentiment shifts, thematic clusters, converging interests,
  and conspicuous absences. Distinguished from brain-drift (which compares
  behavior against stated goals rather than discovering new patterns) and
  brain-graduate (which promotes already-identified recurring themes into concept
  notes rather than discovering them for the first time).
---

# brain-emerge -- Pattern Synthesis

Surface unnamed patterns, implicit directions, or conclusions hidden across scattered vault notes.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Gather Raw Material

Collect data from multiple sources:

a. Recent journal entries (last 30 days). Run against `data/brain.db` using `sqlite3`:
```sql
SELECT date, content, icor_elements, summary, sentiment_score
FROM journal_entries
WHERE date >= date('now', '-30 days')
ORDER BY date DESC;
```

b. Scan vault for unconnected notes:
- Use Glob to find all `.md` files in `vault/Concepts/`, `vault/Inbox/`, `vault/Projects/`
- Read each file's frontmatter and first 500 characters

c. Check for orphan notes (files not linked from any other file):
- Use Grep to search for `[[filename]]` patterns across the vault
- Identify files that are never referenced by other files

### 3. Analyze for Patterns

Look for these pattern types:

**Thematic Clusters:** Topics that appear across multiple unrelated notes but aren't explicitly connected. Example: mentions of "systems thinking" in a fitness log, a project note, and a book highlight.

**Sentiment Shifts:** Gradual changes in emotional tone around a topic. Example: early excitement about a project shifting to frustration over weeks.

**Implicit Priorities:** What the user actually spends time writing about vs what they say matters. The gap reveals unconscious priorities.

**Recurring Questions:** Questions that keep appearing in different forms across entries, suggesting unresolved tensions.

**Converging Interests:** Two or more separate interest threads that are converging but the user hasn't noticed the connection.

**Absent Patterns:** Things conspicuously missing -- goals declared but never journaled about, people mentioned once then forgotten.

### 4. Synthesize Findings

For each discovered pattern:

```markdown
## Emerged Patterns

### Pattern 1: [Descriptive Name]
**Type:** [Thematic Cluster / Sentiment Shift / Implicit Priority / Recurring Question / Convergence / Absence]
**Confidence:** [High / Medium / Low]

**Evidence:**
- [Date]: "[relevant quote]" (source: [file])
- [Date]: "[relevant quote]" (source: [file])
- [Date]: "[relevant quote]" (source: [file])

**What this might mean:**
[AI interpretation of what this pattern suggests about the user's thinking, priorities, or direction]

**Questions to consider:**
- [Reflection question 1]
- [Reflection question 2]

---
```

### 5. Present to User

Show all discovered patterns ranked by confidence. For each, offer:
- Accept: Save as a new concept in `vault/Concepts/`
- Note: Append to today's daily note for reflection
- Dismiss: Acknowledged but not acted on

### 6. Record

For accepted patterns, create concept notes and update SQLite concept_metadata.
For all patterns, log the emergence event in today's daily note.
