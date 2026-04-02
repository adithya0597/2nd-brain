---
type: reference
date: 2026-03-30
source: system
icor_elements: [Systems & Environment]
status: active
tags: [dashboard, visualization, architecture, design-spec]
---

# Second Brain Dashboard — Design Specification

**Date**: 2026-03-30
**Method**: 7 parallel research agents (data inventory, competitive analysis, tech architecture, metric design, graph visualization, UX patterns, project timeline)
**Status**: Spec complete, ready for implementation

---

## Technology Decision: Streamlit

**Winner**: Streamlit (Python-native, direct SQLite, knowledge graph via networkx+plotly, 15 min to first dashboard)

| Criterion | Streamlit | Evidence.dev | Grafana | Datasette |
|---|---|---|---|---|
| SQLite direct | Yes | Yes | Plugin | Yes |
| Python-native | Yes | No (Node) | No | Yes |
| Knowledge graph | Yes (networkx+plotly) | No | No | No |
| Interactivity | Strong (widgets) | Moderate | Strong | Explore only |
| Setup time | 15 min | 25 min | 50 min | 10 min |

**Companion tool**: Datasette for ad-hoc SQL exploration alongside the dashboard.

**Graph visualization**: Cytoscape.js (standalone HTML) for the interactive knowledge graph, embedded via iframe or linked from the Streamlit dashboard. fCoSE layout for community-grouped force-directed positioning.

---

## Dashboard Architecture

### 5 Sections, Progressive Disclosure

Following Shneiderman's mantra (overview first, zoom and filter, details on demand):

**Level 1 — Above the Fold (always visible)**:
- Brain Level gauge (1-10) with component radar
- 6 ICOR dimension status indicators (hot/warm/cold/frozen)
- Journal streak + capture frequency
- Active alert count

**Level 2 — Expandable Sections**:
- Knowledge Graph Health
- ICOR Life Balance
- Engagement & Journaling
- Search & RAG Quality
- System Health

**Level 3 — Drill-Down (on click)**:
- Individual dimension detail
- Node detail in graph
- Specific metric history

---

## Current Data Profile

| Entity | Count | Notes |
|---|---|---|
| Vault documents | 66 | 13 journal, 12 inbox, 10 report, 10 project, 6 dimension |
| Vault edges | 381 | semantic_similarity 145, icor_affinity 98, tag_shared 71, wikilink 67 |
| Communities | 4 | Sizes: 34, 13, 10, 8 |
| Journal entries | 14 | 28-day span, 57% missing mood |
| Captures | 14 | 6/14 = Mind & Growth |
| Engagement daily | 7 | Score range: 2.0-6.8 |
| Brain Level | 6/10 | Consistency 0.65, depth 0.0 |
| API calls | 49 | All Gemini 2.5 Flash, $0.00 cost |
| Action items | 7 | 6 pending, 0 completed |
| Concepts graduated | 0 | |
| Search log | 0 | Table exists, needs population |

---

## Section 1: Brain Score (Above the Fold)

**Layout**: Single row — Brain Level gauge (left) + ICOR radar (center) + streak/alerts (right)

### 1.1 Brain Level Gauge
- **Type**: Radial gauge 1-10 with color zones (1-3 red, 4-6 yellow, 7-10 green)
- **Below gauge**: 5 horizontal bars for component scores (consistency, breadth, depth, growth, momentum)
- **SQL**: `SELECT * FROM brain_level ORDER BY period DESC LIMIT 1`

### 1.2 ICOR Radar Chart
- **Type**: Radar/spider chart, 6 axes (one per dimension)
- **Value**: Latest momentum_score from dimension_signals
- **Color**: Each axis uses its ICOR dimension color
- **SQL**: `SELECT dimension, momentum_score FROM dimension_signals WHERE date = (SELECT MAX(date) FROM dimension_signals)`

### 1.3 Quick Stats Row
- **Type**: 4 metric cards
- Journal streak (current + longest)
- Captures this week
- Pending actions
- Active alerts

---

## Section 2: Knowledge Graph Health

### 2.1 Interactive Graph Visualization
- **Type**: Force-directed graph (Cytoscape.js with fCoSE layout)
- **Nodes**: Colored by ICOR dimension, sized by degree centrality
- **Edges**: Styled by type (solid=wikilink, dashed=affinity, dotted=semantic, double=tag)
- **Communities**: Compound nodes as bounding boxes
- **Interactions**: Click node = side panel with metadata + Obsidian deep link
- **Filters**: Edge type checkboxes, node type checkboxes, ICOR dimension toggles, search

### 2.2 Graph Stats
- **Type**: 4 metric cards
- Documents: 66 | Edges: 381 | Edge density: 5.77/node | Communities: 4

### 2.3 Edge Type Distribution
- **Type**: Donut chart
- **SQL**: `SELECT edge_type, COUNT(*) FROM vault_edges GROUP BY edge_type`

### 2.4 Community Sizes
- **Type**: Horizontal bar chart with dominant ICOR dimension label
- **SQL**: community + icor_affinity join query

### 2.5 Bridge Nodes
- **Type**: Table (top 10 by cross-community connections)

### 2.6 Orphan Documents
- **Type**: Alert badge + expandable list
- **Current**: 1 orphan ("LinkedIn Portfolio")

---

## Section 3: ICOR Life Balance

### 3.1 Dimension Heatmap
- **Type**: Heatmap (6 dimensions x 30 days, color = momentum level)
- **Color scale**: frozen=gray, cold=blue, warm=orange, hot=red
- **SQL**: `SELECT date, dimension, momentum_score FROM dimension_signals WHERE date >= date('now', '-30 days')`

### 3.2 Capture Radar
- **Type**: Radar chart (6 axes = dimensions, value = capture count)
- **SQL**: `SELECT json_each.value AS dimension, COUNT(*) FROM captures_log, json_each(dimensions_json) GROUP BY dimension`

### 3.3 Drift Visualization
- **Type**: Grouped bar chart (stated priority vs actual attention per dimension)

### 3.4 Key Element Treemap
- **Type**: Treemap (dimensions as parents, 23 key elements as children, size = attention_score)

---

## Section 4: Engagement & Journaling

### 4.1 Engagement Sparkline
- **Type**: Area chart (30 days), reference line at 5.0
- **Color**: Score >= 7 green, 4-6 yellow, < 4 red
- **SQL**: `SELECT date, engagement_score FROM engagement_daily WHERE date >= date('now', '-30 days')`

### 4.2 Journal Calendar Heatmap
- **Type**: GitHub-style contribution calendar (90 days)
- **Color**: Has entry = green intensity by word count, no entry = gray

### 4.3 Mood/Energy Trends
- **Type**: Dual-axis line chart (mood numeric 1-5 left, energy 1-3 right)
- **Note**: Sparse data (57% missing mood, 79% missing energy)

### 4.4 Action Pipeline
- **Type**: Horizontal funnel (pending -> in_progress -> completed)
- **Current**: 6 pending, 0 completed

### 4.5 Graduation Pipeline
- **Type**: Status pills (pending/approved/rejected/snoozed/expired)
- **Current**: 0 proposals

---

## Section 5: Search & RAG Quality

**Note**: search_log has 0 rows currently. This section activates as queries accumulate.

### 5.1 Queries Per Day (bar chart)
### 5.2 Channel Contribution (stacked bar)
### 5.3 Response Time Distribution (histogram)
### 5.4 Most Searched Terms (frequency table)
### 5.5 Classification Accuracy (pie chart by method)

---

## Section 6: System Health

### 6.1 Job Status Table
- **Type**: Table with colored health indicators (green/yellow/red)
- **Thresholds**: Daily jobs = 25h, weekly = 170h, biweekly = 340h
- **Current**: 4 stale jobs (emerge, weekly_review, project_summary, notion_sync)

### 6.2 API Token Consumption
- **Type**: Daily stacked bar (input vs output) + cumulative line
- **Current**: 49 calls, 424K tokens, $0.00 (Gemini free tier)

### 6.3 Database Size
- **Type**: Single number + trend (needs snapshot table)
- **Current**: 9.2 MB

### 6.4 Notion Sync Status
- **Type**: Entity table with last sync time + health badge
- **Current**: 1 stuck outbox item in processing state

---

## Section 7: Project Timeline

### 7.1 Sprint Timeline
- **Type**: Plotly Gantt chart (Sprint 1-6 + Week 1-4)

### 7.2 Code Growth
- **Type**: Cumulative line chart (35,367 LoC current)

### 7.3 Test Growth
- **Type**: Line chart (0 -> 943 tests)

### 7.4 Commit Heatmap
- **Type**: GitHub-style calendar (6 active days, 58 commits)

---

## UX Design Principles

1. **Brain Score as progress ring** — top-left, largest visual weight (Apple Health pattern)
2. **Three-layer drill-down** — overview / zoom / detail (Shneiderman's mantra)
3. **Segmented time control** — Today / 7d / 30d / All (not a date picker)
4. **Radar chart for ICOR balance** — Wheel of Life coaching pattern
5. **Streak milestones with grace period** — Duolingo-inspired, 1-day freeze
6. **Dark mode** — `#1a1a2e` background, saturated ICOR dimension colors
7. **Three-tier alerts** — passive (in dashboard), contextual (in briefing), active (push)
8. **Self-competition** — trend arrows and personal bests, not absolute scores
9. **Mobile-first cards** — one thought per card for Telegram
10. **Unicode sparklines for Telegram** — `▁▂▃▄▅▆▇█` block characters

### Color Palette

| Element | Color | Hex |
|---|---|---|
| Background | Dark navy | `#1a1a2e` |
| Surface/cards | Dark blue-gray | `#16213e` |
| Text | Off-white | `#e0e0e0` |
| Health & Vitality | Green | `#4ade80` |
| Wealth & Finance | Gold | `#fbbf24` |
| Relationships | Pink | `#f472b6` |
| Mind & Growth | Blue | `#60a5fa` |
| Purpose & Impact | Purple | `#c084fc` |
| Systems & Environment | Cyan | `#22d3ee` |
| Alert critical | Red | `#ef4444` |
| Alert warning | Amber | `#f59e0b` |

---

## New Infrastructure Needed

### 2 Snapshot Tables (for time-series trending)

```sql
-- graph_health_snapshots (populated by vault_reindex daily)
CREATE TABLE graph_health_snapshots (
    date TEXT PRIMARY KEY,
    doc_node_count INTEGER, total_edge_count INTEGER,
    edges_per_node REAL, orphan_count INTEGER,
    community_count INTEGER, chunk_count INTEGER
);

-- system_health_snapshots (populated by db_backup daily)
CREATE TABLE system_health_snapshots (
    date TEXT PRIMARY KEY,
    db_size_bytes INTEGER, vault_file_count INTEGER,
    total_rows_estimate INTEGER
);
```

### Graph Export Script
`scripts/export_graph.py` — queries vault_nodes + vault_edges, outputs `data/graph.json` for Cytoscape.js.

---

## Implementation Plan

### Phase 1: Streamlit skeleton (1 day)
- `scripts/dashboard.py` with 5 sections using Plotly
- Brain Level gauge + ICOR radar + engagement sparkline + graph stats
- Sidebar filters (time range, edge types)
- `streamlit run scripts/dashboard.py`

### Phase 2: Knowledge graph (1 day)
- `scripts/export_graph.py` for JSON export
- `dashboard/graph.html` with Cytoscape.js + fCoSE
- Side panel with node detail + Obsidian deep link
- Link from Streamlit via iframe or button

### Phase 3: Full metrics (1-2 days)
- All Section 2-6 charts with real SQL queries
- Migration for 2 snapshot tables
- Wire snapshot population into existing scheduled jobs

### Phase 4: Polish (1 day)
- Dark mode theme
- Unicode sparkline formatter for Telegram integration
- Project timeline section
- Personal bests tracking

**Total: ~4-5 days**

---

## Inspirations

| Source | What to Steal |
|---|---|
| Apple Health rings | Brain Level as progress ring |
| Daylio Year in Pixels | Engagement calendar heatmap |
| Thomas Frank Ultimate Brain | Single column + Side Peek for Telegram |
| Duolingo | Streak milestones with freeze grace |
| Exist.io | Correlation discovery ("you journal more on gym days") |
| Gyroscope | Single composite Health Score |
| Strava | Personal records and self-competition |
| Obsidian Graph View | Dark background + glowing nodes |
