---
name: brain-challenge
description: >
  Use this skill when the user wants to stress-test, red-team, or find
  counter-evidence for a belief, assumption, or decision — any request about
  playing devil's advocate, pressure-testing convictions, finding contradictions
  in their own thinking, or checking whether a belief holds up. This includes
  surfacing behavioral gaps where actions contradict stated beliefs, temporal
  inconsistencies, and constructing the strongest possible counter-argument from
  the user's own data. Distinguished from brain-drift (which checks overall
  alignment, not a specific belief) and brain-ghost (which answers AS the user
  in agreement with their perspective rather than arguing against it).
---

# brain-challenge -- Red-Team a Belief

Pressure-test a current belief or assumption by finding contradictions and counter-evidence in the vault history.

## Steps

### 1. Identify the Belief to Challenge

Extract the belief or concept to challenge from the user's message. If no specific belief is provided, auto-detect strong beliefs:

a. Read `vault/Identity/Values.md` for explicitly stated beliefs

b. Run against `data/brain.db` using `sqlite3` for frequently repeated themes:
```sql
SELECT icor_elements, COUNT(*) as frequency
FROM journal_entries
WHERE date >= date('now', '-60 days')
GROUP BY icor_elements
ORDER BY frequency DESC
LIMIT 5;
```

c. Search `vault/Concepts/` for evergreen concepts (status = evergreen)

d. Present the top 5 candidates and ask the user which to challenge

### 2. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 3. Gather the Belief's Foundation

Search for all supporting evidence in the vault:
- Use Grep to find mentions of the belief/concept across all vault files
- Query SQLite for journal entries that affirm or support this belief
- Note the dates and contexts where this belief appears strongest

### 4. Search for Counter-Evidence

Now look for contradictions:

a. **Direct contradictions:** Entries where the user expressed the opposite view. Run against `data/brain.db` using `sqlite3`:
```sql
SELECT date, content, sentiment_score
FROM journal_entries
WHERE content LIKE '%' || '<belief_keywords>' || '%'
ORDER BY sentiment_score ASC
LIMIT 10;
```

b. **Behavioral contradictions:** Times when actions didn't align with the belief
- Check action_items for tasks that contradict the stated belief
- Look for periods where attention to this area dropped despite strong declarations

c. **External counter-evidence:** Notes, web clips, or book highlights that present opposing viewpoints
- Search `vault/` for content tagged with similar ICOR elements but with different conclusions

d. **Temporal inconsistency:** How has this belief changed over time?
- Look for earlier entries where the user held a different position

### 5. Construct the Challenge

```markdown
## Challenge Report: "[Belief Statement]"

### The Belief as Stated
"[The belief in the user's own words, with source and date]"

### Strength of Conviction
- First expressed: [date]
- Times affirmed: [count]
- Last affirmed: [date]
- Supporting evidence points: [count]

### Counter-Evidence Found

#### 1. [Counter-point title]
**Source:** [file, date]
**Quote:** "[contradicting passage]"
**Strength:** [Strong / Moderate / Weak]
**Analysis:** [Why this challenges the belief]

#### 2. [Counter-point title]
...

### Behavioral Gaps
- [Date range]: Despite stating "[belief]", your journal shows [contradicting behavior]
- Action items related to this belief: [completed vs abandoned ratio]

### Devil's Advocate Summary
If someone were arguing against this belief using only YOUR OWN words and data, they would say:
"[Synthesized counter-argument drawn entirely from the user's vault]"

### Reflection Prompts
1. What conditions might this belief be true AND false?
2. What would have to happen for you to change your mind?
3. Is this a belief you chose, or one you inherited?
4. What's the cost of holding this belief if it's wrong?

### Verdict
**Belief robustness:** [Strong / Moderate / Fragile]
- The belief has [X] supporting and [Y] contradicting data points
- Key vulnerability: [the strongest counter-argument]
```

### 6. Output

Present the challenge report to the user. Offer to:
- Save as a note in `vault/Concepts/Challenge-[belief-name].md`
- Append summary to today's daily note
- Update the belief in `vault/Identity/Values.md` if the user wants to revise it
