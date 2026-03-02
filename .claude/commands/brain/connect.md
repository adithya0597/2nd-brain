# /brain:connect — Serendipity Engine

Find unexpected connections between two domains by traversing the vault's link graph and knowledge network.

**Input:** `$ARGUMENTS` — two domains or topics separated by a space (e.g., "Fashion Technology" or "Health Investing")

## Steps

### 1. Parse Domains
Split `$ARGUMENTS` into two domains. If fewer than two provided, ask the user for both domains.

Domain A: [first argument]
Domain B: [second argument]

### 2. Map Domain A
Gather all vault content related to Domain A:

a. Search the vault:
- Use Grep to find all files mentioning Domain A (case-insensitive) in `vault/`
- Check `vault/Concepts/` for concept notes related to Domain A
- Query SQLite for journal entries mentioning Domain A:
```sql
SELECT date, content, icor_elements FROM journal_entries
WHERE content LIKE '%' || '<domain_a>' || '%' ORDER BY date DESC LIMIT 20;
```

b. Map ICOR connections:
- Identify which Key Elements Domain A touches
- Query for the ICOR hierarchy:
```sql
SELECT h.name, p.name AS parent FROM icor_hierarchy h
LEFT JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE h.name LIKE '%' || '<domain_a>' || '%';
```

c. Extract concepts, people, projects, and tags associated with Domain A

### 3. Map Domain B
Repeat the same process for Domain B.

### 4. Find Bridges
Look for connections between the two domains:

a. **Shared ICOR Elements:** Key Elements that appear in both domains' notes
b. **Shared Concepts:** Concept notes referenced by both domains
c. **Shared People:** People who appear in context of both domains
d. **Shared Projects:** Projects that touch both domains
e. **Shared Tags:** Notion tags associated with both domains
f. **Temporal Proximity:** Journal entries about both domains on the same day or consecutive days
g. **Semantic Bridges:** Themes, metaphors, or frameworks that appear in both domains

Query for co-occurrence:
```sql
SELECT a.date, a.content
FROM journal_entries a
WHERE (a.content LIKE '%' || '<domain_a>' || '%')
  AND (a.content LIKE '%' || '<domain_b>' || '%')
ORDER BY a.date DESC;
```

### 5. Generate Connection Map

```markdown
## Connection Map: [Domain A] <-> [Domain B]

### Direct Connections Found: [count]

**Bridge 1: [Connection Name]**
- Domain A side: [how it relates to Domain A]
- Domain B side: [how it relates to Domain B]
- Evidence: "[quote or reference]" (source: [file])
- Connection strength: [Strong / Moderate / Weak]

**Bridge 2: [Connection Name]**
...

### Path Through the Knowledge Graph
```
[Domain A] -> [Intermediate concept 1] -> [Intermediate concept 2] -> [Domain B]
```

Each step explained:
1. [Domain A] connects to [Concept 1] because: [reason]
2. [Concept 1] connects to [Concept 2] because: [reason]
3. [Concept 2] connects to [Domain B] because: [reason]

### Novel Intersection Points
Based on the connections found, here are potential novel ideas at the intersection:

1. **[Idea Name]:** [Description of how combining insights from both domains creates something new]
2. **[Idea Name]:** [Description]
3. **[Idea Name]:** [Description]

### Recommended Explorations
- Read: [specific vault note that bridges both domains]
- Research: [external topic that could deepen the connection]
- Create: [project idea that leverages the intersection]
- Connect with: [person from People DB who relates to both domains]
```

### 6. Output
Present the connection map to the user. Offer to:
- Save as a concept note in `vault/Concepts/Connection-[DomainA]-[DomainB].md`
- Create a new project idea if the intersections are actionable
- Append to today's daily note
