---
name: brain-trace
description: >
  Use this skill when the user wants to follow the evolution of a specific
  concept, idea, or belief over time — any request about how their thinking has
  changed, building a timeline for a topic, or understanding the arc of a
  particular interest. This covers tracing when an idea first appeared, how it
  shifted through journal entries and notes, what sentiment changes occurred, and
  where the concept stands today. Distinguished from brain-find (which locates
  content by query rather than tracking evolution) and brain-emerge (which
  discovers broad patterns across many notes rather than following one concept's
  journey through time).
---

# brain-trace -- Concept Evolution Timeline

Track how a specific concept or idea has evolved over time across the vault.

## Steps

### 1. Identify the Concept

Extract the concept name or topic to trace from the user's message. If no concept is provided, list recent concepts from SQLite.

Run against `data/brain.db` using `sqlite3`:
```sql
SELECT title, status, mention_count, first_mentioned, last_mentioned
FROM concept_metadata
ORDER BY last_mentioned DESC LIMIT 10;
```

If no concept was specified, present this list and ask the user to choose one.

### 2. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 3. Search the Vault

Use Grep to find ALL mentions across the vault:
- Search `vault/` for the concept name (case-insensitive)
- Include Daily Notes, Concepts, Meetings, Projects folders
- Capture surrounding context (3 lines before and after each mention)

### 4. Query SQLite for Structured Data

Run all queries against `data/brain.db` using `sqlite3`:

a. Journal entries mentioning this concept:
```sql
SELECT date, content, mood, sentiment_score, icor_elements
FROM journal_entries
WHERE content LIKE '%' || '<concept>' || '%'
   OR icor_elements LIKE '%' || '<concept>' || '%'
ORDER BY date ASC;
```

b. Concept metadata (if it's a graduated concept):
```sql
SELECT * FROM concept_metadata WHERE title LIKE '%' || '<concept>' || '%';
```

c. Attention trend for related ICOR element:
```sql
SELECT ai.period_start, ai.period_end, ai.mention_count, ai.attention_score
FROM attention_indicators ai
JOIN icor_hierarchy h ON ai.icor_element_id = h.id
WHERE h.name LIKE '%' || '<concept>' || '%'
ORDER BY ai.period_start;
```

### 5. Build Evolution Timeline

Create a chronological timeline showing:

```markdown
## Trace: [Concept Name]

### Timeline

**[YYYY-MM-DD]** -- First mention
> [quote from the first mention]
- Context: [what was happening that day]
- Sentiment: [positive/neutral/negative]

**[YYYY-MM-DD]** -- [Summary of how thinking shifted]
> [relevant quote]
- Position change: [what evolved]

**[YYYY-MM-DD]** -- [Latest mention]
> [quote]
- Current stance: [summary]

### Evolution Summary
- **First appeared:** [date]
- **Total mentions:** [count]
- **Sentiment arc:** [how feelings about this concept have changed]
- **Position shift:** [from X to Y]
- **Related concepts:** [other concepts that co-occur]
- **ICOR mapping:** [which Key Elements this touches]

### Open Questions
- [Questions the user hasn't resolved about this concept]
```

### 6. Output

Present the timeline to the user. If they want, offer to save it as a section in the concept's note file (if one exists in `vault/Concepts/`).
