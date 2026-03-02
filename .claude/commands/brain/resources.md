# /brain:resources — Knowledge Base Catalog

Generate a catalog of your knowledge base: concepts, reference materials, tools, and learning resources organized by type and ICOR dimension.

## Steps

### 1. Gather SQLite Data

a. Evergreen and growing concepts:
```sql
SELECT title, status, mention_count, last_mentioned, first_mentioned,
       icor_elements, summary,
       CAST(julianday('now') - julianday(last_mentioned) AS INTEGER) AS days_since_mention
FROM concept_metadata
WHERE status IN ('evergreen', 'growing')
ORDER BY mention_count DESC;
```

b. Recently added concepts (last 30 days):
```sql
SELECT title, status, mention_count, first_mentioned, icor_elements, summary
FROM concept_metadata
WHERE first_mentioned >= date('now', '-30 days')
ORDER BY first_mentioned DESC;
```

c. Stale concepts (no mention in 60+ days, not archived):
```sql
SELECT title, status, mention_count, last_mentioned, icor_elements, summary,
       CAST(julianday('now') - julianday(last_mentioned) AS INTEGER) AS days_stale
FROM concept_metadata
WHERE status != 'archived'
  AND last_mentioned <= date('now', '-60 days')
ORDER BY days_stale DESC;
```

### 2. Fetch Notion Data

a. **Resource Tags** — Query `collection://231fda46-1a19-8195-8338-000b82b65137` for Tags with Type "Resource". Retrieve: Name, Parent Tag, linked Notes count, linked Projects count.

b. **Reference Notes** — Query `collection://231fda46-1a19-8139-a401-000b477c8cd0` for notes with Type in ("Reference", "Book", "Recipe", "Lecture", "Web Clip"). Retrieve: Name, Type, Tag, Note Date. Group by type.

c. **Recently Added Notes** — Query the Notes collection for notes with Note Date in the last 30 days. Note their types and tags.

d. **Area Tags** — Query Tags collection for Type "Area" to map resources to ICOR dimensions via parent-child tag relationships.

### 3. Categorize & Analyze

Group resources into categories:
- **Books & Reading**: Book-type notes, reading-related concepts
- **Tools & Frameworks**: Resource-tagged tools, technical concepts
- **Templates & Recipes**: Recipe/Template notes, process documentation
- **Learning & Courses**: Lecture/Course notes, growing concepts
- **References & Docs**: Reference notes, Web Clips, documentation

For each category, analyze:
- Total count and recent additions (last 30 days)
- Most referenced items (by mention_count or linked entities)
- Stale items (60+ days without mention)
- ICOR dimension distribution

Across all resources:
- **Knowledge health**: ratio of evergreen to seedling concepts
- **Growth rate**: new concepts per month
- **Staleness score**: % of resources not touched in 60+ days
- **Dimension coverage**: which dimensions have the most/fewest resources

### 4. Generate Catalog

```markdown
## Knowledge Base Catalog — [Date]

**Total resources:** [N] | **Evergreen concepts:** [N] | **New this month:** [N] | **Stale (60d+):** [N]

---

### By Category

#### Books & Reading ([N] items)
| Title | Type | Dimension | Last Referenced | Mentions |
|---|---|---|---|---|
| [Title] | [Book/Reference] | [Dimension] | [Date] | [N] |

**Highlights:** [Most referenced book], [Recently added]

#### Tools & Frameworks ([N] items)
| Title | Type | Dimension | Status | Mentions |
|---|---|---|---|---|
| [Title] | [Tool/Framework] | [Dimension] | [evergreen/growing] | [N] |

#### Templates & Recipes ([N] items)
| Title | Dimension | Last Used | Status |
|---|---|---|---|
| [Title] | [Dimension] | [Date] | [Active/Stale] |

#### Learning & Courses ([N] items)
| Title | Type | Dimension | Started | Progress |
|---|---|---|---|---|
| [Title] | [Lecture/Course] | [Dimension] | [Date] | [seedling/growing] |

#### References & Documentation ([N] items)
| Title | Type | Dimension | Added | Mentions |
|---|---|---|---|---|
| [Title] | [Web Clip/Reference] | [Dimension] | [Date] | [N] |

---

### Recently Added (Last 30 Days)

| Title | Type | Category | Dimension | Date Added |
|---|---|---|---|---|
| [Title] | [Type] | [Category] | [Dimension] | [Date] |

---

### Knowledge Health

| Metric | Value | Status |
|---|---|---|
| Evergreen concepts | [N] | [Good/Needs growth] |
| Growing concepts | [N] | — |
| Seedling concepts | [N] | — |
| Stale resources (60d+) | [N] | [OK/Needs review] |
| Growth rate | [N]/month | [Healthy/Slow] |
| Staleness ratio | [N]% | [Healthy/High] |

---

### Dimension Coverage

| Dimension | Resources | Evergreen | Growing | Seedling | Stale | Health |
|---|---|---|---|---|---|---|
| Health & Vitality | [N] | [N] | [N] | [N] | [N] | [Good/Gap] |
| ... | ... | ... | ... | ... | ... | ... |

---

### Stale Resources for Review

| Title | Type | Last Mentioned | Days Stale | Action |
|---|---|---|---|---|
| [Title] | [Type] | [Date] | [N] | [Archive/Refresh/Keep] |

---

### Suggested Actions

1. [Specific recommendation]
2. [Another recommendation]
3. [...]
```

### 5. Output
Present the resource catalog. Offer to:
- Save as `vault/Concepts/Resource-Catalog-YYYY-MM-DD.md`
- Archive stale concepts in vault (update frontmatter status)
- Create Notion notes for undocumented resources
