# /brain:challenge — Red-Team a Belief

Pressure-test a current belief or assumption by finding contradictions and counter-evidence in the vault history.

**Input:** `$ARGUMENTS` — optional belief or concept to challenge. If empty, auto-detect strong beliefs.

## Steps

### 1. Identify the Belief to Challenge

**If $ARGUMENTS is provided:**
Use it as the belief/concept to challenge.

**If $ARGUMENTS is empty:**
Scan for the user's strongest stated beliefs:
a. Read `vault/Identity/Values.md` for explicitly stated beliefs
b. Query SQLite for frequently repeated themes:
```sql
SELECT icor_elements, COUNT(*) as frequency
FROM journal_entries
WHERE date >= date('now', '-60 days')
GROUP BY icor_elements
ORDER BY frequency DESC
LIMIT 5;
```
c. Check the Context Data for evergreen concepts (status = evergreen) from the concepts query
d. Present the top 5 candidates and ask the user which to challenge

### 2. Gather the Belief's Foundation
Search for all supporting evidence in the provided Context Data:
- Look through the vault files and journal entries provided in the context for mentions of the belief/concept
- Use the journal entries from the Context Data that affirm or support this belief
- Note the dates and contexts where this belief appears strongest

### 3. Search for Counter-Evidence
Now look for contradictions:

a. **Direct contradictions:** Entries where the user expressed the opposite view
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

### 4. Construct the Challenge

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

### 5. Output
Present the challenge report to the user. Offer to:
- Save as a note in `vault/Concepts/Challenge-[belief-name].md`
- Append summary to today's daily note
- Update the belief in `vault/Identity/Values.md` if the user wants to revise it
