---
name: brain-resources
description: >
  Use this skill when the user wants an overview of their entire knowledge base —
  what concepts, books, tools, references, and learning resources they have, how
  healthy the collection is, and where the gaps are. This covers requests to catalog
  or audit the knowledge base, check which concepts are growing vs. stale, see
  resource distribution across ICOR dimensions, or understand the overall health of
  their intellectual capital. Distinguished from brain-find (which searches for a
  specific piece of information) and brain-projects (which tracks active work rather
  than reference material and accumulated knowledge).
---

# brain-resources — Knowledge Base Catalog

Generate a catalog of the knowledge base: concepts, reference materials, tools, and learning resources organized by type and ICOR dimension.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Gather SQLite Data

Run against `data/brain.db` using `sqlite3`:

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

### 3. Fetch Notion Data

a. **Resource Tags** — Query `collection://231fda46-1a19-8195-8338-000b82b65137` for Tags with Type "Resource". Retrieve: Name, Parent Tag, linked Notes count, linked Projects count.

b. **Reference Notes** — Query `collection://231fda46-1a19-8139-a401-000b477c8cd0` for notes with Type in ("Reference", "Book", "Recipe", "Lecture", "Web Clip"). Retrieve: Name, Type, Tag, Note Date. Group by type.

c. **Recently Added Notes** — Query the Notes collection for notes with Note Date in the last 30 days. Note their types and tags.

d. **Area Tags** — Query Tags collection for Type "Area" to map resources to ICOR dimensions via parent-child tag relationships.

### 4. Categorize & Analyze

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

### 5. Generate Catalog

Use the output template in `references/output-template.md` to format the catalog.

### 6. Output

Present the resource catalog. Offer to:
- Save as `vault/Concepts/Resource-Catalog-YYYY-MM-DD.md`
- Archive stale concepts in vault (update frontmatter status)
- Create Notion notes for undocumented resources
