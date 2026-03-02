# /brain:ghost — Digital Twin

Build a persona from vault data and answer a question as the user would. Useful for self-reflection on biases, decision patterns, and blind spots.

**Input:** `$ARGUMENTS` — the question to answer as the user

## Steps

### 1. Parse the Question
The question to answer as the user: `$ARGUMENTS`

If no argument provided, ask the user what question they'd like their digital twin to answer.

### 2. Build the Persona Profile
Gather data to construct the user's decision-making profile:

a. **Values and Beliefs** — Read `vault/Identity/Values.md`

b. **Life Priorities** — Read `vault/Identity/ICOR.md` for their life architecture and stated priorities

c. **Recent Mindset** — Query SQLite for last 30 days of journal entries:
```sql
SELECT date, content, mood, energy, sentiment_score, icor_elements
FROM journal_entries
WHERE date >= date('now', '-30 days')
ORDER BY date DESC;
```

d. **Decision History** — Search the vault for past decisions:
- Use Grep to find entries containing "decided", "chose", "going to", "committed to", "changed my mind"
- Note the reasoning patterns behind these decisions

e. **Communication Style** — Analyze journal entries for:
- Typical sentence structure and vocabulary
- Level of optimism vs pragmatism
- How they weigh pros and cons
- Common phrases or expressions

f. **Active Projects and Goals** — Read `vault/Identity/Active-Projects.md`

### 3. Construct the Ghost Response
Using the assembled persona profile, answer the question as the user would:

```markdown
## Ghost Response

**Question:** "[The question]"

**Your digital twin says:**

> [First-person response written in the user's voice and decision-making style, incorporating their values, current priorities, recent emotional state, and historical patterns]

**Reasoning trace:**
This response is based on:
- Value: "[relevant value from Values.md]"
- Recent pattern: "[relevant journal pattern]" ([date])
- Past decision: "[similar past decision]" ([date])
- Current priority: "[relevant ICOR focus]"

**Confidence:** [High / Medium / Low] — based on how much relevant data was found

**Potential blind spots:**
- [Bias or assumption the ghost response might carry]
- [Alternative perspective the user might be overlooking]
```

### 4. Reflection
Ask the user:
- "Does this sound like you?"
- "What surprised you about this response?"
- "What would you change about how your twin answered?"

If the user identifies discrepancies, suggest updating Values.md or journaling about the insight.
