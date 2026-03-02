# /brain:context-load — Load Session Context

Pre-load the Second Brain context for this session. This establishes who the user is, what they're working on, and what needs attention.

## Steps

1. **Read Identity Files**
   - Read `vault/Identity/ICOR.md` — the user's life architecture
   - Read `vault/Identity/Values.md` — core values and beliefs
   - Read `vault/Identity/Active-Projects.md` — current project index

2. **Query SQLite for Recent State**
   Run these queries against `data/brain.db` using `sqlite3`:

   a. Last 7 days of journal summaries:
   ```sql
   SELECT date, summary, mood, energy, icor_elements FROM journal_entries WHERE date >= date('now', '-7 days') ORDER BY date DESC;
   ```

   b. Pending action items:
   ```sql
   SELECT id, description, source_date, icor_element, icor_project FROM action_items WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20;
   ```

   c. Attention flags (neglected Key Elements):
   ```sql
   SELECT h.name, p.name AS dimension, h.last_mentioned,
          CAST(julianday('now') - julianday(h.last_mentioned) AS INTEGER) AS days_since
   FROM icor_hierarchy h
   JOIN icor_hierarchy p ON h.parent_id = p.id
   WHERE h.level = 'key_element'
     AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days'))
   ORDER BY h.last_mentioned ASC NULLS FIRST;
   ```

   d. Active concepts:
   ```sql
   SELECT title, status, mention_count FROM concept_metadata WHERE status != 'archived' ORDER BY last_mentioned DESC LIMIT 10;
   ```

3. **Output Context Summary**
   Present a compressed summary:
   - User's ICOR dimensions and current focus areas
   - Active projects and their statuses
   - Recent journal themes (from summaries)
   - Pending actions count and top priorities
   - Attention alerts for neglected Key Elements
   - Active concepts being developed

This context is now loaded. The user can proceed with their session.
