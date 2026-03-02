-- ============================================================
-- Second Brain — Common SQL Query Patterns
-- Reference file for /brain:* commands
-- Database: data/brain.db
-- ============================================================

-- ============================================================
-- JOURNAL QUERIES
-- ============================================================

-- Recent journal entries (last 7 days)
-- Used by: /brain:context-load, /brain:today
SELECT date, content, mood, energy, icor_elements, summary
FROM journal_entries
WHERE date >= date('now', '-7 days')
ORDER BY date DESC;

-- Journal entries for a specific date
-- Used by: /brain:close-day
SELECT id, content, mood, energy, icor_elements
FROM journal_entries
WHERE date = date('now')
ORDER BY created_at;

-- Journal entries for drift analysis (last 30-60 days)
-- Used by: /brain:drift
SELECT date, content, icor_elements, sentiment_score
FROM journal_entries
WHERE date >= date('now', '-60 days')
ORDER BY date;

-- Journal entries mentioning a specific ICOR element
-- Used by: /brain:trace
SELECT date, content, summary, sentiment_score
FROM journal_entries
WHERE icor_elements LIKE '%' || :element_name || '%'
ORDER BY date;

-- ============================================================
-- ACTION ITEM QUERIES
-- ============================================================

-- Pending action items
-- Used by: /brain:context-load, /brain:today
SELECT id, description, source_file, source_date, icor_element, icor_project
FROM action_items
WHERE status = 'pending'
ORDER BY created_at DESC;

-- Yesterday's unfinished actions
-- Used by: /brain:today
SELECT id, description, source_file, icor_element
FROM action_items
WHERE status = 'pending'
  AND source_date = date('now', '-1 day');

-- Actions ready to push to Notion
-- Used by: /brain:sync-notion
SELECT id, description, icor_element, icor_project
FROM action_items
WHERE status = 'pending'
  AND external_id IS NULL;

-- ============================================================
-- ICOR HIERARCHY QUERIES
-- ============================================================

-- Full ICOR hierarchy tree
-- Used by: /brain:context-load, /brain:drift
SELECT h.id, h.level, h.name, p.name AS parent_name,
       h.attention_score, h.last_mentioned, h.notion_page_id
FROM icor_hierarchy h
LEFT JOIN icor_hierarchy p ON h.parent_id = p.id
ORDER BY h.id;

-- Dimensions with their Key Elements
-- Used by: /brain:drift, /brain:refresh-dashboard
SELECT d.name AS dimension, ke.name AS key_element,
       ke.attention_score, ke.last_mentioned
FROM icor_hierarchy d
JOIN icor_hierarchy ke ON ke.parent_id = d.id
WHERE d.level = 'dimension' AND ke.level = 'key_element'
ORDER BY d.id, ke.id;

-- Neglected key elements (no mention in 7+ days)
-- Used by: /brain:today, /brain:refresh-dashboard
SELECT h.id, h.name, p.name AS dimension, h.last_mentioned,
       julianday('now') - julianday(h.last_mentioned) AS days_since
FROM icor_hierarchy h
JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE h.level = 'key_element'
  AND (h.last_mentioned IS NULL OR h.last_mentioned < date('now', '-7 days'))
ORDER BY h.last_mentioned ASC NULLS FIRST;

-- ============================================================
-- ATTENTION INDICATOR QUERIES
-- ============================================================

-- Current attention scores (latest period)
-- Used by: /brain:refresh-dashboard
SELECT ai.icor_element_id, h.name, ai.mention_count,
       ai.journal_days, ai.attention_score, ai.flagged
FROM attention_indicators ai
JOIN icor_hierarchy h ON ai.icor_element_id = h.id
WHERE ai.period_end = (SELECT MAX(period_end) FROM attention_indicators)
ORDER BY ai.attention_score DESC;

-- Attention trend for a specific element
-- Used by: /brain:trace
SELECT period_start, period_end, mention_count,
       attention_score, flagged
FROM attention_indicators
WHERE icor_element_id = :element_id
ORDER BY period_start;

-- ============================================================
-- CONCEPT QUERIES
-- ============================================================

-- All active concepts by status
-- Used by: /brain:context-load
SELECT title, status, mention_count, last_mentioned, icor_elements
FROM concept_metadata
WHERE status != 'archived'
ORDER BY last_mentioned DESC;

-- Concept graduation candidates (mentioned 3+ times in last 14 days)
-- Used by: /brain:graduate
SELECT DISTINCT je.icor_elements
FROM journal_entries je
WHERE je.date >= date('now', '-14 days')
  AND je.icor_elements != '[]';

-- Concept evolution timeline
-- Used by: /brain:trace
SELECT cm.title, cm.first_mentioned, cm.last_mentioned,
       cm.mention_count, cm.status, cm.summary
FROM concept_metadata cm
WHERE cm.title LIKE '%' || :concept_name || '%';

-- ============================================================
-- SYNC LOG QUERIES
-- ============================================================

-- Recent sync operations
-- Used by: /brain:sync-notion
SELECT operation, source_file, target, status, details, created_at
FROM vault_sync_log
ORDER BY created_at DESC
LIMIT 20;

-- Failed syncs
SELECT operation, source_file, target, details, created_at
FROM vault_sync_log
WHERE status = 'failed'
ORDER BY created_at DESC;

-- ============================================================
-- AGGREGATE / DASHBOARD QUERIES
-- ============================================================

-- ICOR element mention distribution (last 30 days)
-- Used by: /brain:drift, /brain:refresh-dashboard
WITH element_mentions AS (
    SELECT json_each.value AS element_name, COUNT(*) AS mention_count
    FROM journal_entries, json_each(journal_entries.icor_elements)
    WHERE journal_entries.date >= date('now', '-30 days')
    GROUP BY json_each.value
)
SELECT h.name AS key_element, p.name AS dimension,
       COALESCE(em.mention_count, 0) AS mentions_30d
FROM icor_hierarchy h
JOIN icor_hierarchy p ON h.parent_id = p.id
LEFT JOIN element_mentions em ON em.element_name = h.name
WHERE h.level = 'key_element'
ORDER BY mentions_30d DESC;

-- Daily journal consistency (last 30 days)
SELECT COUNT(DISTINCT date) AS days_journaled,
       30 AS total_days,
       ROUND(COUNT(DISTINCT date) * 100.0 / 30, 1) AS consistency_pct
FROM journal_entries
WHERE date >= date('now', '-30 days');

-- Sentiment trend (last 30 days)
SELECT date, AVG(sentiment_score) AS avg_sentiment
FROM journal_entries
WHERE date >= date('now', '-30 days')
  AND sentiment_score IS NOT NULL
GROUP BY date
ORDER BY date;

-- ============================================================
-- IDEA GENERATION QUERIES
-- ============================================================

-- Seedling and growing concepts (idea candidates)
-- Used by: /brain:ideas
SELECT title, status, mention_count, last_mentioned,
       first_mentioned, icor_elements, summary
FROM concept_metadata
WHERE status IN ('seedling', 'growing')
ORDER BY last_mentioned DESC;

-- Recurring themes in recent journal entries (60 days)
-- Used by: /brain:ideas
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

-- Stale pending actions (potential idea triggers)
-- Used by: /brain:ideas
SELECT description, source_file, source_date, icor_element, icor_project
FROM action_items
WHERE status = 'pending'
  AND source_date <= date('now', '-14 days')
ORDER BY source_date ASC;

-- ICOR elements by attention gap (stated importance vs actual focus)
-- Used by: /brain:ideas
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

-- ============================================================
-- SCHEDULING / ENERGY PATTERN QUERIES
-- ============================================================

-- Energy patterns by day of week (historical averages)
-- Used by: /brain:schedule
SELECT
    CASE CAST(strftime('%w', date) AS INTEGER)
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
    END AS day_name,
    CAST(strftime('%w', date) AS INTEGER) AS day_num,
    COUNT(*) AS entries,
    ROUND(AVG(CASE energy WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END), 1) AS avg_energy,
    ROUND(AVG(sentiment_score), 2) AS avg_sentiment,
    ROUND(AVG(CASE mood
        WHEN 'great' THEN 5 WHEN 'good' THEN 4 WHEN 'okay' THEN 3
        WHEN 'low' THEN 2 WHEN 'bad' THEN 1 END), 1) AS avg_mood
FROM journal_entries
WHERE date >= date('now', '-90 days')
GROUP BY day_num
ORDER BY day_num;

-- Pending actions with ICOR context for scheduling
-- Used by: /brain:schedule
SELECT ai.id, ai.description, ai.source_date, ai.icor_element, ai.icor_project,
       h.name AS element_name, p.name AS dimension_name,
       CAST(julianday('now') - julianday(ai.source_date) AS INTEGER) AS age_days
FROM action_items ai
LEFT JOIN icor_hierarchy h ON ai.icor_element = h.name
LEFT JOIN icor_hierarchy p ON h.parent_id = p.id
WHERE ai.status = 'pending'
ORDER BY ai.source_date ASC;

-- ICOR dimension coverage for target week planning
-- Used by: /brain:schedule
SELECT p.name AS dimension,
       COUNT(DISTINCT ai.id) AS pending_actions,
       COUNT(DISTINCT CASE WHEN ai.source_date >= date('now', '-7 days') THEN ai.id END) AS recent_actions,
       MAX(h.attention_score) AS max_attention,
       MIN(COALESCE(h.last_mentioned, '2000-01-01')) AS oldest_mention
FROM icor_hierarchy p
LEFT JOIN icor_hierarchy h ON h.parent_id = p.id AND h.level = 'key_element'
LEFT JOIN action_items ai ON ai.icor_element = h.name AND ai.status = 'pending'
WHERE p.level = 'dimension'
GROUP BY p.name
ORDER BY pending_actions DESC;
