"""Block Kit message builders for Slack."""
from datetime import datetime


def _section(text: str) -> dict:
    """Helper: create a markdown section block."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _header(text: str) -> dict:
    """Helper: create a header block."""
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _divider() -> dict:
    return {"type": "divider"}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _button(text: str, action_id: str, value: str, style: str = None) -> dict:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "action_id": action_id,
        "value": value,
    }
    if style in ("primary", "danger"):
        btn["style"] = style
    return btn


# ---------------------------------------------------------------------------
# Morning Briefing
# ---------------------------------------------------------------------------

def format_morning_briefing(data: dict) -> list[dict]:
    """Build Block Kit blocks for the morning briefing.

    Expected data keys:
        - date: str (YYYY-MM-DD)
        - carried_over: list[dict] with "description", "icor_element"
        - active_projects: list[dict] with "name", "status", "goal"
        - neglected: list[dict] with "key_element", "dimension", "last_activity"
        - suggestions: list[str]
    """
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    blocks = [
        _header(f"Morning Briefing - {date_str}"),
    ]

    # Carried over actions
    carried = data.get("carried_over", [])
    if carried:
        items = "\n".join(
            f"- [ ] {a['description']}" + (f" _({a.get('icor_element', '')})_" if a.get("icor_element") else "")
            for a in carried
        )
        blocks.append(_section(f"*Carried Over Actions:*\n{items}"))
    else:
        blocks.append(_section("*Carried Over Actions:* None - clean slate!"))

    blocks.append(_divider())

    # Active projects
    projects = data.get("active_projects", [])
    if projects:
        items = "\n".join(
            f"- *{p['name']}* - {p.get('status', 'N/A')}"
            + (f" ({p['goal']})" if p.get("goal") else "")
            for p in projects
        )
        blocks.append(_section(f"*Active Projects:*\n{items}"))

    blocks.append(_divider())

    # Attention alerts
    neglected = data.get("neglected", [])
    if neglected:
        items = "\n".join(
            f"- :warning: *{n['key_element']}* ({n['dimension']}) - {n.get('last_activity', 'unknown')}"
            for n in neglected
        )
        blocks.append(_section(f"*Attention Alerts:*\n{items}"))

    blocks.append(_divider())

    # Suggestions
    suggestions = data.get("suggestions", [])
    if suggestions:
        items = "\n".join(f"{i+1}. {s}" for i, s in enumerate(suggestions))
        blocks.append(_section(f"*Suggested Focus Areas:*\n{items}"))

    blocks.append(_context(f"Generated at {datetime.now().strftime('%H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Evening Review
# ---------------------------------------------------------------------------

def format_evening_review(data: dict) -> list[dict]:
    """Build Block Kit blocks for the evening review.

    Expected data keys:
        - date: str
        - completed_actions: list[dict]
        - new_actions: list[dict]
        - journal_summary: str
        - mood: str
        - energy: str
        - icor_touched: list[str]
        - icor_missed: list[str]
    """
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    blocks = [
        _header(f"Evening Review - {date_str}"),
    ]

    # Completed actions
    completed = data.get("completed_actions", [])
    if completed:
        items = "\n".join(f"- :white_check_mark: {a['description']}" for a in completed)
        blocks.append(_section(f"*Completed Today:*\n{items}"))
    else:
        blocks.append(_section("*Completed Today:* Nothing marked complete."))

    blocks.append(_divider())

    # New actions extracted
    new_actions = data.get("new_actions", [])
    if new_actions:
        items = "\n".join(f"- [ ] {a['description']}" for a in new_actions)
        blocks.append(_section(f"*New Actions Extracted:*\n{items}"))

    # Journal summary
    summary = data.get("journal_summary", "")
    if summary:
        blocks.append(_divider())
        blocks.append(_section(f"*Journal Summary:*\n{summary}"))

    # Mood/Energy
    mood = data.get("mood", "")
    energy = data.get("energy", "")
    if mood or energy:
        parts = []
        if mood:
            parts.append(f"Mood: {mood}")
        if energy:
            parts.append(f"Energy: {energy}")
        blocks.append(_context(" | ".join(parts)))

    blocks.append(_divider())

    # ICOR coverage
    touched = data.get("icor_touched", [])
    missed = data.get("icor_missed", [])
    if touched:
        blocks.append(_section(f"*Dimensions Touched:* {', '.join(touched)}"))
    if missed:
        blocks.append(_section(f"*Dimensions Missed:* {', '.join(missed)}"))

    blocks.append(_context(f"Generated at {datetime.now().strftime('%H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Action Item (with interactive buttons)
# ---------------------------------------------------------------------------

def format_action_item(action: dict) -> list[dict]:
    """Build Block Kit blocks for a single action with buttons.

    Expected action keys:
        - id: int
        - description: str
        - icor_element: str (optional)
        - icor_project: str (optional)
        - source_date: str (optional)
    """
    action_id = str(action.get("id", ""))
    desc = action.get("description", "No description")
    element = action.get("icor_element", "")
    project = action.get("icor_project", "")

    text = f"*{desc}*"
    if element:
        text += f"\n:label: {element}"
    if project:
        text += f" | :file_folder: {project}"

    blocks = [
        _section(text),
        {
            "type": "actions",
            "elements": [
                _button("Complete", "complete_action", action_id, "primary"),
                _button("Snooze", "snooze_action", action_id),
                _button("Delegate", "delegate_action", action_id),
            ],
        },
    ]

    source_date = action.get("source_date", "")
    if source_date:
        blocks.append(_context(f"Created: {source_date}"))

    return blocks


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def format_dashboard(icor_data: dict, projects: list, actions: list) -> list[dict]:
    """Build Block Kit blocks for the ICOR heatmap dashboard.

    Args:
        icor_data: Dict with dimension names -> list of key elements with scores.
        projects: List of active projects.
        actions: List of pending action counts or summaries.
    """
    blocks = [
        _header("ICOR Dashboard"),
    ]

    # Heatmap by dimension
    for dimension, elements in icor_data.items():
        element_lines = []
        for el in elements:
            score = el.get("attention_score", 0)
            # Simple heatmap: high=green, mid=yellow, low=red
            if score >= 7:
                indicator = ":large_green_circle:"
            elif score >= 4:
                indicator = ":large_yellow_circle:"
            else:
                indicator = ":red_circle:"
            element_lines.append(f"  {indicator} {el['name']} ({score:.1f})")

        blocks.append(_section(f"*{dimension}*\n" + "\n".join(element_lines)))

    blocks.append(_divider())

    # Active projects
    if projects:
        proj_lines = "\n".join(f"- *{p['name']}* ({p.get('status', 'N/A')})" for p in projects[:10])
        blocks.append(_section(f"*Active Projects ({len(projects)}):*\n{proj_lines}"))

    # Pending actions count
    if actions:
        blocks.append(_context(f"Pending actions: {len(actions)}"))

    blocks.append(_context(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Drift Report
# ---------------------------------------------------------------------------

def format_drift_report(drift_data: dict) -> list[dict]:
    """Build Block Kit blocks for drift analysis.

    Expected drift_data keys:
        - summary: str
        - aligned: list[dict] with "element", "expected", "actual"
        - drifted: list[dict] with "element", "expected", "actual", "direction"
        - recommendations: list[str]
    """
    blocks = [
        _header("Alignment Drift Report"),
    ]

    summary = drift_data.get("summary", "")
    if summary:
        blocks.append(_section(summary))

    blocks.append(_divider())

    # Aligned elements
    aligned = drift_data.get("aligned", [])
    if aligned:
        items = "\n".join(f"- :white_check_mark: *{a['element']}*" for a in aligned)
        blocks.append(_section(f"*Aligned:*\n{items}"))

    # Drifted elements
    drifted = drift_data.get("drifted", [])
    if drifted:
        items = "\n".join(
            f"- :warning: *{d['element']}* - {d.get('direction', 'off-track')}"
            for d in drifted
        )
        blocks.append(_section(f"*Needs Attention:*\n{items}"))

    blocks.append(_divider())

    # Recommendations
    recs = drift_data.get("recommendations", [])
    if recs:
        items = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs))
        blocks.append(_section(f"*Recommendations:*\n{items}"))

    blocks.append(_context(f"Analysis period: 60 days | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Ideas Report
# ---------------------------------------------------------------------------

def format_ideas_report(ideas: list) -> list[dict]:
    """Build Block Kit blocks for idea generation report.

    Each idea dict: "title", "description", "source", "icor_element" (optional)
    """
    blocks = [
        _header("Idea Generation Report"),
    ]

    if not ideas:
        blocks.append(_section("No new ideas surfaced in this cycle."))
        return blocks

    for i, idea in enumerate(ideas, 1):
        text = f"*{i}. {idea.get('title', 'Untitled')}*\n{idea.get('description', '')}"
        if idea.get("icor_element"):
            text += f"\n:label: {idea['icor_element']}"
        if idea.get("source"):
            text += f"\n_Source: {idea['source']}_"
        blocks.append(_section(text))
        if i < len(ideas):
            blocks.append(_divider())

    blocks.append(_context(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Capture Confirmation
# ---------------------------------------------------------------------------

def format_capture_confirmation(text: str, dimensions: list[str], channels: list[str]) -> list[dict]:
    """Confirmation message after routing a capture.

    Args:
        text: The captured message text.
        dimensions: List of matched dimension names (may be empty for uncategorized).
        channels: List of target channel names (may be empty for uncategorized).
    """
    if dimensions and channels:
        dim_text = " + ".join(dimensions)
        ch_text = ", ".join(f"#{c}" for c in channels)
        return [
            _section(":white_check_mark: *Captured and routed*"),
            _section(f"> {text[:200]}{'...' if len(text) > 200 else ''}"),
            _context(f"Dimensions: {dim_text} | Routed to: {ch_text}"),
        ]
    else:
        return [
            _section(":inbox_tray: *Captured to inbox*"),
            _section(f"> {text[:200]}{'...' if len(text) > 200 else ''}"),
            _context("No dimension matched — saved to inbox for manual review"),
        ]


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

def format_help() -> list[dict]:
    """Build Block Kit blocks listing all slash commands."""
    commands = [
        ("/brain-today", "Morning review + daily note", "#brain-daily"),
        ("/brain-close", "Evening review + journal index", "#brain-daily"),
        ("/brain-schedule", "Energy-aware weekly planning", "#brain-daily"),
        ("/brain-drift", "Goal vs. journal alignment analysis", "#brain-insights"),
        ("/brain-ideas", "Actionable idea generation from vault", "#brain-insights"),
        ("/brain-emerge", "Surface hidden patterns from notes", "#brain-insights"),
        ("/brain-ghost", "Digital twin answers a question", "#brain-insights"),
        ("/brain-trace", "Track concept evolution over time", "#brain-insights"),
        ("/brain-connect", "Find connections between two domains", "#brain-insights"),
        ("/brain-challenge", "Red-team a belief with counter-evidence", "#brain-insights"),
        ("/brain-graduate", "Promote journal themes to concepts", "#brain-insights"),
        ("/brain-projects", "Active project dashboard", "#brain-daily"),
        ("/brain-resources", "Knowledge base catalog", "#brain-daily"),
        ("/brain-review", "GTD weekly review", "#brain-daily"),
        ("/brain-find", "Semantic vault search", "DM"),
        ("/brain-cost", "API token usage & cost dashboard", "#brain-dashboard"),
        ("/brain-status", "Quick SQLite status dashboard", "#brain-dashboard"),
        ("/brain-sync", "Bidirectional Notion sync", "DM"),
        ("/brain-context", "Load session context", "DM"),
        ("/brain-help", "This help message", "DM"),
    ]

    blocks = [_header("Second Brain Commands")]

    lines = []
    for cmd, desc, channel in commands:
        lines.append(f"`{cmd}` — {desc} → _{channel}_")

    blocks.append(_section("\n".join(lines)))
    blocks.append(_divider())
    blocks.append(_section(
        "*Tips:*\n"
        "- Most commands accept optional text input (e.g. `/brain-trace mindfulness`)\n"
        "- `/brain-sync tasks,projects` syncs only specific entity types\n"
        "- Captures in #brain-inbox are auto-classified and routed"
    ))
    blocks.append(_context(f"Second Brain v1.0 | {datetime.now().strftime('%Y-%m-%d')}"))
    return blocks


def format_health_check(checks: dict) -> list:
    """Format startup health check results as Slack blocks."""
    blocks = [
        _header("Bot Startup Health Check"),
        _divider(),
    ]
    for name, status in checks.items():
        if "FAIL" in status:
            emoji = ":x:"
        elif "WARN" in status:
            emoji = ":warning:"
        else:
            emoji = ":white_check_mark:"
        blocks.append(_section(f"{emoji} *{name}*: {status}"))
    blocks.append(_context(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


def format_cost_report(data: dict, days: int = 30) -> list[dict]:
    """Build Block Kit blocks for the API cost report.

    Expected data keys:
        - daily: list[dict] with "date", "calls", "daily_cost", "input_tokens", "output_tokens"
        - by_caller: list[dict] with "caller", "calls", "total_cost", "avg_input", "avg_output"
        - by_model: list[dict] with "model", "calls", "total_cost"
    """
    blocks = [
        _header(f"API Cost Report (Last {days} Days)"),
    ]

    daily = data.get("daily", [])
    by_caller = data.get("by_caller", [])
    by_model = data.get("by_model", [])

    # Summary stats
    total_cost = sum(r.get("daily_cost", 0) or 0 for r in daily)
    total_calls = sum(r.get("calls", 0) or 0 for r in daily)
    avg_cost = total_cost / total_calls if total_calls else 0

    blocks.append(_section(
        f"*Total cost:* ${total_cost:.4f} | *Total calls:* {total_calls} | *Avg cost/call:* ${avg_cost:.4f}"
    ))

    blocks.append(_divider())

    # Daily breakdown (last 7 days from daily data)
    if daily:
        lines = []
        for row in daily[:7]:
            date = row.get("date", "?")
            calls = row.get("calls", 0)
            cost = row.get("daily_cost", 0) or 0
            inp = row.get("input_tokens", 0) or 0
            out = row.get("output_tokens", 0) or 0
            lines.append(f"`{date}` — {calls} calls, ${cost:.4f}, {inp:,} in / {out:,} out")
        blocks.append(_section("*Daily Breakdown*\n" + "\n".join(lines)))
    else:
        blocks.append(_section("*Daily Breakdown*\nNo API calls in this period."))

    blocks.append(_divider())

    # Top callers
    if by_caller:
        lines = []
        for row in by_caller[:10]:
            caller = row.get("caller", "?")
            calls = row.get("calls", 0)
            cost = row.get("total_cost", 0) or 0
            avg_in = int(row.get("avg_input", 0) or 0)
            avg_out = int(row.get("avg_output", 0) or 0)
            lines.append(f"  `{caller}` — {calls} calls, ${cost:.4f} (avg {avg_in:,} in / {avg_out:,} out)")
        blocks.append(_section("*Top Callers*\n" + "\n".join(lines)))

    blocks.append(_divider())

    # Model breakdown
    if by_model:
        lines = []
        for row in by_model:
            model = row.get("model", "?")
            calls = row.get("calls", 0)
            cost = row.get("total_cost", 0) or 0
            lines.append(f"  `{model}` — {calls} calls, ${cost:.4f}")
        blocks.append(_section("*Model Breakdown*\n" + "\n".join(lines)))

    blocks.append(_context(f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


def format_search_results(
    query: str,
    results: list,
    channels_used: list[str],
    total: int,
) -> list[dict]:
    """Build Block Kit blocks for hybrid search results.

    Args:
        query: The original search query.
        results: List of SearchResult objects (file_path, title, score, snippet, sources).
        channels_used: Which search channels contributed results.
        total: Total candidate count before dedup/limit.
    """
    blocks = [
        _header(f"Search: \"{query}\""),
        _context(f"Channels: {', '.join(channels_used)} | {total} candidates | {len(results)} results"),
        _divider(),
    ]

    for i, r in enumerate(results[:15]):
        # Format source badges
        source_list = r.sources if hasattr(r, 'sources') else []
        source_badges = " ".join(f"`{s}`" for s in source_list)

        title = r.title if hasattr(r, 'title') else ""
        file_path = r.file_path if hasattr(r, 'file_path') else ""
        snippet = r.snippet if hasattr(r, 'snippet') else ""

        text = f"*{i+1}. {title}*"
        if file_path:
            text += f"\n`{file_path}`"
        if snippet:
            text += f"\n{snippet}"
        if source_badges:
            text += f"\n{source_badges}"

        blocks.append(_section(text))

    if not results:
        blocks.append(_section("No results found. Try different keywords or `/brain-find --ai <query>` for AI-powered search."))

    blocks.append(_divider())
    blocks.append(_context(f"Use `/brain-find --ai {query}` for AI-summarized results"))

    return blocks


def format_error(message: str) -> list[dict]:
    """Error message block."""
    return [
        _section(f":x: *Error*\n{message}"),
    ]


# ---------------------------------------------------------------------------
# Projects Dashboard
# ---------------------------------------------------------------------------

def format_projects_dashboard(projects: list, tasks: list, dimensions: list) -> list[dict]:
    """Build Block Kit blocks for the project dashboard.

    Args:
        projects: List of dicts with "name", "status", "goal", "dimension",
                  "done_tasks", "total_tasks", "blocked", "deadline".
        tasks: List of blocked/overdue task dicts with "description", "project", "age_days".
        dimensions: List of dicts with "dimension", "project_count", "pending_tasks",
                    "attention_score", "status".
    """
    blocks = [
        _header("Project Dashboard"),
    ]

    # Summary stats
    active_count = len(projects)
    total_tasks = sum(p.get("total_tasks", 0) for p in projects)
    blocked_count = len(tasks)
    blocks.append(_section(
        f"*Active projects:* {active_count} | *Tasks pending:* {total_tasks} | *Blocked items:* {blocked_count}"
    ))

    blocks.append(_divider())

    # Projects by status
    for status_label in ("Doing", "Planned", "Ongoing"):
        status_projects = [p for p in projects if p.get("status", "").lower() == status_label.lower()]
        if not status_projects:
            continue

        status_emoji = {"Doing": ":hammer_and_wrench:", "Planned": ":clipboard:", "Ongoing": ":repeat:"}.get(status_label, ":file_folder:")
        lines = []
        for p in status_projects:
            name = p.get("name", "Untitled")
            goal = p.get("goal", "—")
            dim = p.get("dimension", "—")
            done = p.get("done_tasks", 0)
            total = p.get("total_tasks", 0)
            blocked = p.get("blocked", 0)
            deadline = p.get("deadline", "—")

            line = f"• *{name}*"
            if goal != "—":
                line += f" → {goal}"
            line += f"\n  {dim} | {done}/{total} tasks"
            if blocked > 0:
                line += f" | :warning: {blocked} blocked"
            if deadline != "—":
                line += f" | Due: {deadline}"
            lines.append(line)

        blocks.append(_section(f"{status_emoji} *{status_label}*\n\n" + "\n\n".join(lines)))

    blocks.append(_divider())

    # Cross-dimensional view
    if dimensions:
        dim_lines = []
        for d in dimensions:
            dim_name = d.get("dimension", "Unknown")
            proj_count = d.get("project_count", 0)
            pending = d.get("pending_tasks", 0)
            score = d.get("attention_score", 0)
            status = d.get("status", "—")

            status_emoji = {"Balanced": ":white_check_mark:", "Overloaded": ":warning:", "Gap": ":red_circle:"}.get(status, ":white_circle:")
            dim_lines.append(f"  {status_emoji} *{dim_name}* — {proj_count} projects, {pending} tasks pending (attn: {score:.1f})")

        blocks.append(_section("*Cross-Dimensional View*\n\n" + "\n".join(dim_lines)))

    blocks.append(_divider())

    # Blocked/overdue items
    if tasks:
        task_lines = "\n".join(
            f"- :warning: *{t.get('description', 'N/A')[:80]}* — {t.get('project', '?')} ({t.get('age_days', '?')}d)"
            for t in tasks[:10]
        )
        blocks.append(_section(f"*Blocked & Overdue*\n{task_lines}"))
    else:
        blocks.append(_section(":white_check_mark: *No blocked or overdue items*"))

    blocks.append(_context(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Resources Catalog
# ---------------------------------------------------------------------------

def format_resources_catalog(resources: list, concepts: list, recently_added: list) -> list[dict]:
    """Build Block Kit blocks for the resource catalog.

    Args:
        resources: List of dicts with "title", "type", "dimension", "mentions", "status".
        concepts: List of concept dicts with "title", "status", "mention_count",
                  "last_mentioned", "icor_elements".
        recently_added: List of dicts with "title", "type", "dimension", "date_added".
    """
    blocks = [
        _header("Knowledge Base Catalog"),
    ]

    # Summary stats
    total = len(resources)
    evergreen = sum(1 for c in concepts if c.get("status") == "evergreen")
    growing = sum(1 for c in concepts if c.get("status") == "growing")
    seedling = sum(1 for c in concepts if c.get("status") == "seedling")
    new_count = len(recently_added)

    blocks.append(_section(
        f"*Total resources:* {total} | *Evergreen:* {evergreen} | *Growing:* {growing} | *Seedling:* {seedling} | *New this month:* {new_count}"
    ))

    blocks.append(_divider())

    # Resources grouped by type
    type_groups: dict[str, list] = {}
    for r in resources:
        rtype = r.get("type", "Other")
        type_groups.setdefault(rtype, []).append(r)

    type_emojis = {
        "Book": ":books:", "Reference": ":bookmark:", "Tool": ":wrench:",
        "Template": ":page_facing_up:", "Recipe": ":memo:", "Lecture": ":mortar_board:",
        "Course": ":mortar_board:", "Web Clip": ":link:", "Framework": ":gear:",
    }

    for rtype, items in type_groups.items():
        emoji = type_emojis.get(rtype, ":file_folder:")
        lines = []
        for item in items[:8]:
            title = item.get("title", "Untitled")
            dim = item.get("dimension", "—")
            mentions = item.get("mentions", 0)
            lines.append(f"  • *{title}* — {dim} ({mentions} mentions)")

        extra = f"\n  _...and {len(items) - 8} more_" if len(items) > 8 else ""
        blocks.append(_section(f"{emoji} *{rtype}* ({len(items)})\n\n" + "\n".join(lines) + extra))

    blocks.append(_divider())

    # Recently added
    if recently_added:
        recent_lines = "\n".join(
            f"- *{r.get('title', 'Untitled')}* ({r.get('type', '?')}) — {r.get('dimension', '?')} | {r.get('date_added', '?')}"
            for r in recently_added[:10]
        )
        blocks.append(_section(f"*Recently Added (30 days)*\n{recent_lines}"))

    blocks.append(_divider())

    # Knowledge health (concepts)
    if concepts:
        health_lines = [
            f"  :large_green_circle: Evergreen: {evergreen}",
            f"  :large_yellow_circle: Growing: {growing}",
            f"  :seedling: Seedling: {seedling}",
        ]
        blocks.append(_section("*Knowledge Health*\n\n" + "\n".join(health_lines)))

    blocks.append(_context(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks


# ---------------------------------------------------------------------------
# Notion Sync Report
# ---------------------------------------------------------------------------

def format_sync_report(result) -> list[dict]:
    """Build Block Kit blocks for a Notion sync report.

    Args:
        result: SyncResult dataclass with sync counts, errors, and warnings.
    """
    has_errors = bool(result.errors)
    status_emoji = ":warning:" if has_errors else ":white_check_mark:"
    status_text = "Completed with errors" if has_errors else "Completed successfully"

    blocks = [
        _header(f"Notion Sync {status_text}"),
    ]

    # Sync counts
    counts = []
    if result.tasks_pushed:
        counts.append(f":arrow_up: Tasks pushed: {result.tasks_pushed}")
    if result.tasks_status_synced:
        counts.append(f":arrows_counterclockwise: Task statuses synced: {result.tasks_status_synced}")
    if result.projects_pulled:
        counts.append(f":arrow_down: Projects pulled: {result.projects_pulled}")
    if result.goals_pulled:
        counts.append(f":arrow_down: Goals pulled: {result.goals_pulled}")
    if result.tags_synced:
        counts.append(f":label: Tags synced: {result.tags_synced}")
    if result.notes_pushed:
        counts.append(f":arrow_up: Journal notes pushed: {result.notes_pushed}")
    if result.concepts_pushed:
        counts.append(f":arrow_up: Concepts pushed: {result.concepts_pushed}")
    if result.people_synced:
        counts.append(f":busts_in_silhouette: People synced: {result.people_synced}")
    if result.ai_calls:
        counts.append(f":brain: AI decisions: {result.ai_calls}")

    if counts:
        blocks.append(_section("*Sync Summary*\n" + "\n".join(counts)))
    else:
        blocks.append(_section("No changes needed — everything is in sync."))

    # Errors
    if result.errors:
        blocks.append(_divider())
        error_text = "\n".join(f":x: {e}" for e in result.errors[:10])
        if len(result.errors) > 10:
            error_text += f"\n_...and {len(result.errors) - 10} more errors_"
        blocks.append(_section(f"*Errors ({len(result.errors)})*\n{error_text}"))

    # Warnings
    if result.warnings:
        blocks.append(_divider())
        warning_text = "\n".join(f":warning: {w}" for w in result.warnings[:10])
        if len(result.warnings) > 10:
            warning_text += f"\n_...and {len(result.warnings) - 10} more warnings_"
        blocks.append(_section(f"*Warnings ({len(result.warnings)})*\n{warning_text}"))

    blocks.append(_context(f"{status_emoji} Sync completed at {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    return blocks
