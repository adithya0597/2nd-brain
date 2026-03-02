# Second Brain Database — Schema Documentation

Database: `data/brain.db` (SQLite)

## Overview

The SQLite database serves as the structured data layer for the AI-Powered Local Second Brain. It stores parsed journal data, action items, concept metadata, the ICOR life-management hierarchy, attention tracking indicators, and sync logs for Notion integration.

## Tables

### `journal_entries`

Stores parsed content from daily Obsidian journal notes. Each entry represents one day's journal content (or a section thereof).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID |
| date | TEXT NOT NULL | ISO date (YYYY-MM-DD) |
| content | TEXT NOT NULL | Raw journal text |
| mood | TEXT | Detected or declared mood |
| energy | TEXT | Energy level (high/medium/low) |
| icor_elements | TEXT (JSON) | Array of ICOR Key Element names mentioned |
| summary | TEXT | AI-generated summary |
| sentiment_score | REAL | Sentiment analysis score (-1.0 to 1.0) |
| file_path | TEXT | Path to source Obsidian file |
| created_at | TEXT | Timestamp of record creation |

**Indexes:** `date`, `file_path`
**Used by:** `/brain:today`, `/brain:close-day`, `/brain:drift`, `/brain:context-load`, `/brain:trace`

---

### `action_items`

Tracks action items extracted from journal entries, meeting notes, or manually added. Supports lifecycle from pending through completion or push to Notion.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID |
| description | TEXT NOT NULL | Action item text |
| source_file | TEXT | Originating file path |
| source_date | TEXT | Date the action was created |
| status | TEXT | One of: pending, in_progress, completed, cancelled, pushed_to_notion |
| icor_element | TEXT | Associated ICOR Key Element |
| icor_project | TEXT | Associated ICOR project name |
| external_id | TEXT | Notion page ID or other external ID |
| external_system | TEXT | External system name (e.g., 'notion_tasks') |
| created_at | TEXT | Timestamp of record creation |
| completed_at | TEXT | Timestamp of completion |

**Indexes:** `status`, `source_date`, `icor_element`
**Used by:** `/brain:today`, `/brain:close-day`, `/brain:sync-notion`, `/brain:context-load`

---

### `concept_metadata`

Tracks recurring concepts/themes that appear across journal entries. Concepts graduate from seedling to growing to evergreen status as they accumulate mentions.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID |
| title | TEXT UNIQUE | Concept name |
| file_path | TEXT | Path to dedicated concept note (if graduated) |
| status | TEXT | One of: seedling, growing, evergreen |
| icor_elements | TEXT (JSON) | Array of related ICOR Key Elements |
| first_mentioned | TEXT | Date of first appearance |
| last_mentioned | TEXT | Date of most recent appearance |
| mention_count | INTEGER | Total number of mentions |
| related_concepts | TEXT (JSON) | Array of related concept titles |
| summary | TEXT | AI-generated concept summary |
| created_at | TEXT | Timestamp of record creation |

**Indexes:** `status`, `title`
**Used by:** `/brain:graduate`, `/brain:context-load`, `/brain:trace`

---

### `icor_hierarchy`

The core life-management framework. Stores a tree structure: dimensions > key elements > goals > projects > habits. Each node can optionally link to a Notion page for two-way sync.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID (dimensions: 1-6, key elements: 101-603) |
| level | TEXT NOT NULL | One of: dimension, key_element, goal, project, habit |
| name | TEXT NOT NULL | Display name |
| parent_id | INTEGER FK | References parent icor_hierarchy.id |
| description | TEXT | Purpose and scope |
| status | TEXT | Free-form status (active, paused, completed, etc.) |
| notion_page_id | TEXT | Linked Notion page ID |
| attention_score | REAL | Current attention score (0.0+) |
| last_mentioned | TEXT | Date of most recent journal mention |
| created_at | TEXT | Timestamp of record creation |

**Indexes:** `level`, `parent_id`, `notion_page_id`
**Used by:** `/brain:drift`, `/brain:today`, `/brain:sync-notion`, `/brain:context-load`, `/brain:trace`

**Seeded data:** 6 dimensions and 23 key elements are pre-populated by `init-db.sh`.

---

### `attention_indicators`

Periodic snapshots of attention distribution across ICOR key elements. Used to detect neglected areas and track focus over time.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID |
| icor_element_id | INTEGER FK | References icor_hierarchy.id |
| period_start | TEXT NOT NULL | Start of measurement period |
| period_end | TEXT NOT NULL | End of measurement period |
| mention_count | INTEGER | Number of journal mentions in period |
| journal_days | INTEGER | Number of distinct days mentioned |
| attention_score | REAL | Calculated attention score |
| flagged | INTEGER | 1 if element is neglected |
| calculated_at | TEXT | Timestamp of calculation |

**Indexes:** `icor_element_id`, `(period_start, period_end)`
**Used by:** `/brain:drift`, `/brain:refresh-dashboard`, `/brain:trace`

---

### `vault_sync_log`

Audit trail for all synchronization operations between the local vault and Notion.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-incrementing ID |
| operation | TEXT NOT NULL | Operation type (push_task, pull_project, push_icor, pull_goal, etc.) |
| source_file | TEXT | Local file involved |
| target | TEXT | Notion page ID or target file path |
| status | TEXT | One of: success, failed, skipped |
| details | TEXT | Additional context or error message |
| created_at | TEXT | Timestamp of operation |

**Indexes:** `operation`, `created_at`
**Used by:** `/brain:sync-notion`

## Supporting Files

### `notion-registry.json`

Maps local ICOR hierarchy IDs to Notion page IDs. Updated automatically by `/brain:sync-notion`. Includes sections for dimensions, key_elements, goals, projects, and the dashboard page.

### `../scripts/common-queries.sql`

Documented SQL query patterns used by the `/brain:*` commands. Organized by category: journal, action items, ICOR hierarchy, attention indicators, concepts, sync log, and aggregate/dashboard queries.

## Initialization

Run from the project root:

```bash
./scripts/init-db.sh
```

This creates the database, all tables with indexes, and seeds the ICOR hierarchy with 6 dimensions and 23 key elements.
