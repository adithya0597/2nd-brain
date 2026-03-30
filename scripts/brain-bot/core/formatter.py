"""Telegram HTML message builders for Second Brain bot."""

import json
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ---------------------------------------------------------------------------
# Slack :emoji: → Unicode mapping
# ---------------------------------------------------------------------------

_EMOJI: dict[str, str] = {
    ":warning:": "\u26a0\ufe0f",
    ":white_check_mark:": "\u2705",
    ":label:": "\U0001f3f7\ufe0f",
    ":file_folder:": "\U0001f4c1",
    ":large_green_circle:": "\U0001f7e2",
    ":large_yellow_circle:": "\U0001f7e1",
    ":red_circle:": "\U0001f534",
    ":inbox_tray:": "\U0001f4e5",
    ":x:": "\u274c",
    ":hammer_and_wrench:": "\U0001f6e0\ufe0f",
    ":clipboard:": "\U0001f4cb",
    ":repeat:": "\U0001f501",
    ":white_circle:": "\u26aa",
    ":seedling:": "\U0001f331",
    ":books:": "\U0001f4da",
    ":bookmark:": "\U0001f516",
    ":wrench:": "\U0001f527",
    ":page_facing_up:": "\U0001f4c4",
    ":memo:": "\U0001f4dd",
    ":mortar_board:": "\U0001f393",
    ":link:": "\U0001f517",
    ":gear:": "\u2699\ufe0f",
    ":arrow_up:": "\u2b06\ufe0f",
    ":arrows_counterclockwise:": "\U0001f504",
    ":arrow_down:": "\u2b07\ufe0f",
    ":busts_in_silhouette:": "\U0001f465",
    ":brain:": "\U0001f9e0",
    ":fire:": "\U0001f525",
    ":sunny:": "\u2600\ufe0f",
    ":snowflake:": "\u2744\ufe0f",
    ":ice_cube:": "\U0001f9ca",
    ":chart_with_upwards_trend:": "\U0001f4c8",
    ":arrow_right:": "\u27a1\ufe0f",
    ":chart_with_downwards_trend:": "\U0001f4c9",
    ":question:": "\u2753",
    ":large_blue_circle:": "\U0001f535",
    ":bar_chart:": "\U0001f4ca",
    ":bulb:": "\U0001f4a1",
    ":pushpin:": "\U0001f4cc",
}

# Type alias for all format function return values
FormatResult = tuple[str, InlineKeyboardMarkup | None]

# Divider line used between sections
_DIV = "\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"


def _e(text: str) -> str:
    """Replace any remaining Slack :emoji: tokens with Unicode equivalents."""
    for slack, uni in _EMOJI.items():
        text = text.replace(slack, uni)
    return text


def _esc(text: str) -> str:
    """Escape HTML special characters in user-supplied text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cb(data: dict) -> str:
    """Encode callback data dict as compact JSON string for InlineKeyboardButton."""
    return json.dumps(data, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 1. Morning Briefing
# ---------------------------------------------------------------------------

def format_morning_briefing(data: dict) -> FormatResult:
    """Format the morning briefing as Telegram HTML.

    Expected data keys:
        - date, carried_over, active_projects, neglected, suggestions
    """
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    parts = [f"<b>\u2600\ufe0f Morning Briefing \u2014 {date_str}</b>"]

    # Carried over actions
    carried = data.get("carried_over", [])
    if carried:
        items = "\n".join(
            f"\u2022 {_esc(a['description'])}"
            + (f" <i>({_esc(a.get('icor_element', ''))})</i>" if a.get("icor_element") else "")
            for a in carried
        )
        parts.append(f"\n<b>Carried Over Actions:</b>\n{items}")
    else:
        parts.append("\n<b>Carried Over Actions:</b> None \u2014 clean slate!")

    parts.append(_DIV)

    # Active projects
    projects = data.get("active_projects", [])
    if projects:
        items = "\n".join(
            f"\u2022 <b>{_esc(p['name'])}</b> \u2014 {_esc(p.get('status', 'N/A'))}"
            + (f" ({_esc(p['goal'])})" if p.get("goal") else "")
            for p in projects
        )
        parts.append(f"<b>Active Projects:</b>\n{items}")

    parts.append(_DIV)

    # Attention alerts
    neglected = data.get("neglected", [])
    if neglected:
        items = "\n".join(
            f"\u2022 \u26a0\ufe0f <b>{_esc(n['key_element'])}</b> ({_esc(n['dimension'])}) \u2014 {_esc(n.get('last_activity', 'unknown'))}"
            for n in neglected
        )
        parts.append(f"<b>Attention Alerts:</b>\n{items}")

    parts.append(_DIV)

    # Suggestions
    suggestions = data.get("suggestions", [])
    if suggestions:
        items = "\n".join(f"{i+1}. {_esc(s)}" for i, s in enumerate(suggestions))
        parts.append(f"<b>Suggested Focus Areas:</b>\n{items}")

    parts.append(f"\n<i>Generated at {datetime.now().strftime('%H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 2. Evening Review
# ---------------------------------------------------------------------------

def format_evening_review(data: dict) -> FormatResult:
    """Format the evening review as Telegram HTML.

    Expected data keys:
        - date, completed_actions, new_actions, journal_summary,
          mood, energy, icor_touched, icor_missed
    """
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    parts = [f"<b>\U0001f319 Evening Review \u2014 {date_str}</b>"]

    # Completed actions
    completed = data.get("completed_actions", [])
    if completed:
        items = "\n".join(f"\u2022 \u2705 {_esc(a['description'])}" for a in completed)
        parts.append(f"\n<b>Completed Today:</b>\n{items}")
    else:
        parts.append("\n<b>Completed Today:</b> Nothing marked complete.")

    parts.append(_DIV)

    # New actions extracted
    new_actions = data.get("new_actions", [])
    if new_actions:
        items = "\n".join(f"\u2022 {_esc(a['description'])}" for a in new_actions)
        parts.append(f"<b>New Actions Extracted:</b>\n{items}")

    # Journal summary
    summary = data.get("journal_summary", "")
    if summary:
        parts.append(_DIV)
        parts.append(f"<b>Journal Summary:</b>\n{_esc(summary)}")

    # Mood/Energy
    mood = data.get("mood", "")
    energy = data.get("energy", "")
    if mood or energy:
        meta = []
        if mood:
            meta.append(f"Mood: {_esc(mood)}")
        if energy:
            meta.append(f"Energy: {_esc(energy)}")
        parts.append(f"\n<i>{' | '.join(meta)}</i>")

    parts.append(_DIV)

    # ICOR coverage
    touched = data.get("icor_touched", [])
    missed = data.get("icor_missed", [])
    if touched:
        parts.append(f"<b>Dimensions Touched:</b> {', '.join(_esc(t) for t in touched)}")
    if missed:
        parts.append(f"<b>Dimensions Missed:</b> {', '.join(_esc(m) for m in missed)}")

    parts.append(f"\n<i>Generated at {datetime.now().strftime('%H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 3. Action Item (with interactive buttons)
# ---------------------------------------------------------------------------

def format_action_item(action: dict) -> FormatResult:
    """Format a single action item with Complete/Snooze/Delegate buttons.

    Expected action keys:
        - id, description, icor_element (opt), icor_project (opt), source_date (opt)
    """
    action_id = action.get("id", "")
    desc = _esc(action.get("description", "No description"))
    element = action.get("icor_element", "")
    project = action.get("icor_project", "")

    text = f"<b>{desc}</b>"
    if element:
        text += f"\n\U0001f3f7\ufe0f {_esc(element)}"
    if project:
        text += f" | \U0001f4c1 {_esc(project)}"

    source_date = action.get("source_date", "")
    if source_date:
        text += f"\n<i>Created: {_esc(source_date)}</i>"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Complete", callback_data=_cb({"a": "complete", "id": action_id})),
            InlineKeyboardButton("\u23f0 Snooze", callback_data=_cb({"a": "snooze", "id": action_id})),
            InlineKeyboardButton("\U0001f4e4 Delegate", callback_data=_cb({"a": "delegate", "id": action_id})),
        ]
    ])

    return text, keyboard


# ---------------------------------------------------------------------------
# 4. Action List
# ---------------------------------------------------------------------------

def format_action_list(actions: list[dict]) -> FormatResult:
    """Format a list of pending action items.

    Each action dict: id, description, icor_element (opt), source_date (opt)
    """
    if not actions:
        return "<b>Pending Actions:</b> None \u2014 all clear! \u2705", None

    parts = [f"<b>Pending Actions ({len(actions)})</b>"]
    for i, a in enumerate(actions, 1):
        desc = _esc(a.get("description", "No description"))
        line = f"{i}. {desc}"
        if a.get("icor_element"):
            line += f"  <i>({_esc(a['icor_element'])})</i>"
        parts.append(line)

    parts.append(f"\n<i>Generated at {datetime.now().strftime('%H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 5. Capture Confirmation
# ---------------------------------------------------------------------------

def format_capture_confirmation(text: str, dimensions: list[str], channels: list[str]) -> FormatResult:
    """Confirmation message after routing a capture.

    Args:
        text: The captured message text.
        dimensions: Matched dimension names (may be empty).
        channels: Target channel names (may be empty).
    """
    preview = _esc(text[:200]) + ("..." if len(text) > 200 else "")

    if dimensions and channels:
        dim_text = " + ".join(_esc(d) for d in dimensions)
        ch_text = ", ".join(f"#{_esc(c)}" for c in channels)
        html = (
            f"\u2705 <b>Captured and routed</b>\n\n"
            f"<blockquote>{preview}</blockquote>\n"
            f"<i>Dimensions: {dim_text} | Routed to: {ch_text}</i>"
        )
    else:
        html = (
            f"\U0001f4e5 <b>Captured to inbox</b>\n\n"
            f"<blockquote>{preview}</blockquote>\n"
            f"<i>No dimension matched \u2014 saved to inbox for manual review</i>"
        )
    return html, None


# ---------------------------------------------------------------------------
# 6. Classification Feedback
# ---------------------------------------------------------------------------

def format_classification_feedback(
    text: str,
    dimension: str,
    confidence: float,
    method: str,
) -> FormatResult:
    """Format classification result with Correct/Wrong feedback buttons.

    Args:
        text: Classified message text.
        dimension: Assigned dimension name.
        confidence: Classification confidence (0-1).
        method: Classification method used (keyword/embedding/llm).
    """
    preview = _esc(text[:150]) + ("..." if len(text) > 150 else "")
    pct = f"{confidence * 100:.0f}%"
    html = (
        f"<b>Classified:</b> {_esc(dimension)} ({pct})\n"
        f"<i>Method: {_esc(method)}</i>\n\n"
        f"<blockquote>{preview}</blockquote>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Correct", callback_data=_cb({"a": "fb_correct"})),
            InlineKeyboardButton("\u274c Wrong", callback_data=_cb({"a": "fb_wrong"})),
        ]
    ])
    return html, keyboard


# ---------------------------------------------------------------------------
# 7. Drift Report
# ---------------------------------------------------------------------------

def format_drift_report(drift_data: dict) -> FormatResult:
    """Format drift analysis as Telegram HTML.

    Expected drift_data keys:
        - summary, aligned, drifted, recommendations
    """
    parts = ["<b>\U0001f9ed Alignment Drift Report</b>"]

    summary = drift_data.get("summary", "")
    if summary:
        parts.append(f"\n{_esc(summary)}")

    parts.append(_DIV)

    # Aligned elements
    aligned = drift_data.get("aligned", [])
    if aligned:
        items = "\n".join(f"\u2022 \u2705 <b>{_esc(a['element'])}</b>" for a in aligned)
        parts.append(f"<b>Aligned:</b>\n{items}")

    # Drifted elements
    drifted = drift_data.get("drifted", [])
    if drifted:
        items = "\n".join(
            f"\u2022 \u26a0\ufe0f <b>{_esc(d['element'])}</b> \u2014 {_esc(d.get('direction', 'off-track'))}"
            for d in drifted
        )
        parts.append(f"\n<b>Needs Attention:</b>\n{items}")

    parts.append(_DIV)

    # Recommendations
    recs = drift_data.get("recommendations", [])
    if recs:
        items = "\n".join(f"{i+1}. {_esc(r)}" for i, r in enumerate(recs))
        parts.append(f"<b>Recommendations:</b>\n{items}")

    parts.append(f"\n<i>Analysis period: 60 days | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 8. Ideas Report
# ---------------------------------------------------------------------------

def format_ideas_report(ideas: list) -> FormatResult:
    """Format idea generation report as Telegram HTML.

    Each idea dict: title, description, source (opt), icor_element (opt)
    """
    parts = ["<b>\U0001f4a1 Idea Generation Report</b>"]

    if not ideas:
        parts.append("\nNo new ideas surfaced in this cycle.")
        return "\n".join(parts), None

    for i, idea in enumerate(ideas, 1):
        title = _esc(idea.get("title", "Untitled"))
        desc = _esc(idea.get("description", ""))
        entry = f"\n<b>{i}. {title}</b>\n{desc}"
        if idea.get("icor_element"):
            entry += f"\n\U0001f3f7\ufe0f {_esc(idea['icor_element'])}"
        if idea.get("source"):
            entry += f"\n<i>Source: {_esc(idea['source'])}</i>"
        parts.append(entry)
        if i < len(ideas):
            parts.append(_DIV)

    parts.append(f"\n<i>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 9. Projects Dashboard
# ---------------------------------------------------------------------------

def format_projects_dashboard(projects: list, tasks: list, dimensions: list) -> FormatResult:
    """Format project dashboard as Telegram HTML.

    Args:
        projects: List of project dicts (name, status, goal, dimension, done_tasks,
                  total_tasks, blocked, deadline).
        tasks: Blocked/overdue task dicts (description, project, age_days).
        dimensions: Dimension dicts (dimension, project_count, pending_tasks,
                    attention_score, status).
    """
    parts = ["<b>\U0001f4ca Project Dashboard</b>"]

    # Summary stats
    active_count = len(projects)
    total_tasks = sum(p.get("total_tasks", 0) for p in projects)
    blocked_count = len(tasks)
    parts.append(
        f"\n<b>Active projects:</b> {active_count} | "
        f"<b>Tasks pending:</b> {total_tasks} | "
        f"<b>Blocked items:</b> {blocked_count}"
    )

    parts.append(_DIV)

    # Projects by status
    status_emojis = {
        "Doing": "\U0001f6e0\ufe0f",
        "Planned": "\U0001f4cb",
        "Ongoing": "\U0001f501",
    }
    for status_label in ("Doing", "Planned", "Ongoing"):
        status_projects = [p for p in projects if p.get("status", "").lower() == status_label.lower()]
        if not status_projects:
            continue

        emoji = status_emojis.get(status_label, "\U0001f4c1")
        lines = []
        for p in status_projects:
            name = _esc(p.get("name", "Untitled"))
            goal = _esc(p.get("goal", "\u2014"))
            dim = _esc(p.get("dimension", "\u2014"))
            done = p.get("done_tasks", 0)
            total = p.get("total_tasks", 0)
            blocked = p.get("blocked", 0)
            deadline = _esc(p.get("deadline", "\u2014"))

            line = f"\u2022 <b>{name}</b>"
            if goal != "\u2014":
                line += f" \u2192 {goal}"
            line += f"\n  {dim} | {done}/{total} tasks"
            if blocked > 0:
                line += f" | \u26a0\ufe0f {blocked} blocked"
            if deadline != "\u2014":
                line += f" | Due: {deadline}"
            lines.append(line)

        parts.append(f"{emoji} <b>{status_label}</b>\n\n" + "\n\n".join(lines))

    parts.append(_DIV)

    # Cross-dimensional view
    if dimensions:
        status_icons = {
            "Balanced": "\u2705",
            "Overloaded": "\u26a0\ufe0f",
            "Gap": "\U0001f534",
        }
        dim_lines = []
        for d in dimensions:
            dim_name = _esc(d.get("dimension", "Unknown"))
            proj_count = d.get("project_count", 0)
            pending = d.get("pending_tasks", 0)
            score = d.get("attention_score", 0)
            status = d.get("status", "\u2014")
            icon = status_icons.get(status, "\u26aa")
            dim_lines.append(
                f"  {icon} <b>{dim_name}</b> \u2014 {proj_count} projects, "
                f"{pending} tasks pending (attn: {score:.1f})"
            )
        parts.append(f"<b>Cross-Dimensional View</b>\n\n" + "\n".join(dim_lines))

    parts.append(_DIV)

    # Blocked/overdue items
    if tasks:
        task_lines = "\n".join(
            f"\u2022 \u26a0\ufe0f <b>{_esc(t.get('description', 'N/A')[:80])}</b> "
            f"\u2014 {_esc(t.get('project', '?'))} ({t.get('age_days', '?')}d)"
            for t in tasks[:10]
        )
        parts.append(f"<b>Blocked &amp; Overdue</b>\n{task_lines}")
    else:
        parts.append("\u2705 <b>No blocked or overdue items</b>")

    parts.append(f"\n<i>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 10. Resources Catalog
# ---------------------------------------------------------------------------

def format_resources_catalog(resources: list, concepts: list, recently_added: list) -> FormatResult:
    """Format resource catalog as Telegram HTML.

    Args:
        resources: Resource dicts (title, type, dimension, mentions, status).
        concepts: Concept dicts (title, status, mention_count, last_mentioned, icor_elements).
        recently_added: Recent resource dicts (title, type, dimension, date_added).
    """
    parts = ["<b>\U0001f4da Knowledge Base Catalog</b>"]

    # Summary stats
    total = len(resources)
    evergreen = sum(1 for c in concepts if c.get("status") == "evergreen")
    growing = sum(1 for c in concepts if c.get("status") == "growing")
    seedling = sum(1 for c in concepts if c.get("status") == "seedling")
    new_count = len(recently_added)

    parts.append(
        f"\n<b>Total:</b> {total} | <b>Evergreen:</b> {evergreen} | "
        f"<b>Growing:</b> {growing} | <b>Seedling:</b> {seedling} | "
        f"<b>New this month:</b> {new_count}"
    )

    parts.append(_DIV)

    # Resources grouped by type
    type_groups: dict[str, list] = {}
    for r in resources:
        rtype = r.get("type", "Other")
        type_groups.setdefault(rtype, []).append(r)

    type_emojis = {
        "Book": "\U0001f4da",
        "Reference": "\U0001f516",
        "Tool": "\U0001f527",
        "Template": "\U0001f4c4",
        "Recipe": "\U0001f4dd",
        "Lecture": "\U0001f393",
        "Course": "\U0001f393",
        "Web Clip": "\U0001f517",
        "Framework": "\u2699\ufe0f",
    }

    for rtype, items in type_groups.items():
        emoji = type_emojis.get(rtype, "\U0001f4c1")
        lines = []
        for item in items[:8]:
            title = _esc(item.get("title", "Untitled"))
            dim = _esc(item.get("dimension", "\u2014"))
            mentions = item.get("mentions", 0)
            lines.append(f"  \u2022 <b>{title}</b> \u2014 {dim} ({mentions} mentions)")

        extra = f"\n  <i>...and {len(items) - 8} more</i>" if len(items) > 8 else ""
        parts.append(f"{emoji} <b>{_esc(rtype)}</b> ({len(items)})\n\n" + "\n".join(lines) + extra)

    parts.append(_DIV)

    # Recently added
    if recently_added:
        recent_lines = "\n".join(
            f"\u2022 <b>{_esc(r.get('title', 'Untitled'))}</b> "
            f"({_esc(r.get('type', '?'))}) \u2014 {_esc(r.get('dimension', '?'))} | {_esc(r.get('date_added', '?'))}"
            for r in recently_added[:10]
        )
        parts.append(f"<b>Recently Added (30 days)</b>\n{recent_lines}")

    parts.append(_DIV)

    # Knowledge health
    if concepts:
        health_lines = [
            f"  \U0001f7e2 Evergreen: {evergreen}",
            f"  \U0001f7e1 Growing: {growing}",
            f"  \U0001f331 Seedling: {seedling}",
        ]
        parts.append(f"<b>Knowledge Health</b>\n\n" + "\n".join(health_lines))

    parts.append(f"\n<i>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 11. Search Results
# ---------------------------------------------------------------------------

def format_search_results(
    query: str,
    results: list,
    channels_used: list[str],
    total: int,
) -> FormatResult:
    """Format hybrid search results as Telegram HTML.

    Args:
        query: The original search query.
        results: List of SearchResult objects (file_path, title, score, snippet, sources).
        channels_used: Which search channels contributed.
        total: Total candidate count before dedup/limit.
    """
    parts = [
        f'<b>\U0001f50d Search: "{_esc(query)}"</b>',
        f"<i>Channels: {', '.join(_esc(c) for c in channels_used)} | "
        f"{total} candidates | {len(results)} results</i>",
    ]
    parts.append(_DIV)

    for i, r in enumerate(results[:15]):
        source_list = r.sources if hasattr(r, "sources") else []
        source_badges = " ".join(f"<code>{_esc(s)}</code>" for s in source_list)

        title = _esc(r.title) if hasattr(r, "title") else ""
        file_path = r.file_path if hasattr(r, "file_path") else ""
        snippet = _esc(r.snippet) if hasattr(r, "snippet") else ""

        entry = f"<b>{i+1}. {title}</b>"
        if file_path:
            entry += f"\n<code>{_esc(file_path)}</code>"
        if snippet:
            entry += f"\n{snippet}"
        if source_badges:
            entry += f"\n{source_badges}"
        parts.append(entry)

    if not results:
        parts.append("No results found. Try different keywords or <code>/brain-find --ai</code> for AI-powered search.")

    parts.append(_DIV)
    parts.append(f"<i>Use <code>/brain-find --ai {_esc(query)}</code> for AI-summarized results</i>")

    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 12. Engagement Report
# ---------------------------------------------------------------------------

def format_engagement_report(data: dict) -> FormatResult:
    """Format engagement dashboard as Telegram HTML."""
    parts = ["<b>\U0001f4c8 Engagement Dashboard</b>"]

    # Brain Level gauge
    brain_level = data.get("brain_level", [])
    if brain_level:
        bl = brain_level[0] if isinstance(brain_level, list) else brain_level
        level = bl.get("level", 0) if isinstance(bl, dict) else 0
        filled = round(level)
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        parts.append(f"\n<b>Brain Level:</b> <code>{bar}</code> <b>{level}/10</b>")

    parts.append(_DIV)

    # Dimension momentum grid
    signals = data.get("dimension_signals", [])
    if signals:
        momentum_map = {
            "hot": "\U0001f525",
            "warm": "\u2600\ufe0f",
            "cold": "\u2744\ufe0f",
            "frozen": "\U0001f9ca",
        }
        trend_map = {
            "rising": "\U0001f4c8",
            "stable": "\u27a1\ufe0f",
            "declining": "\U0001f4c9",
        }
        lines = []
        for s in signals:
            dim = _esc(s.get("dimension", "?"))
            mom = s.get("momentum", "cold")
            trend = s.get("trend", "stable")
            tp = s.get("touchpoints", 0)
            icon = momentum_map.get(mom, "\u2753")
            trend_icon = trend_map.get(trend, "\u27a1\ufe0f")
            lines.append(f"{icon} <b>{dim}:</b> {_esc(mom)} ({tp} touches) {trend_icon}")
        parts.append(f"<b>Dimension Momentum</b>\n" + "\n".join(lines))
        parts.append(_DIV)

    # 7-day engagement trend
    engagement = data.get("engagement_7d", [])
    if engagement:
        days = list(reversed(engagement))
        scores = [d.get("engagement_score", 0) for d in days]
        dates = [d.get("date", "?")[-5:] for d in days]
        max_score = max(scores) if scores else 1
        bars = []
        for date, score in zip(dates, scores):
            bar_len = round((score / max(max_score, 1)) * 8)
            bar = "\u2593" * bar_len + "\u2591" * (8 - bar_len)
            bars.append(f"<code>{date}</code> <code>{bar}</code> {score:.1f}")
        parts.append(f"<b>7-Day Engagement</b>\n" + "\n".join(bars))
        parts.append(_DIV)

    # Active alerts
    alerts = data.get("active_alerts", [])
    if alerts:
        severity_icon = {
            "critical": "\U0001f534",
            "warning": "\U0001f7e1",
            "info": "\U0001f535",
        }
        alert_lines = []
        for a in alerts[:5]:
            icon = severity_icon.get(a.get("severity", "info"), "\u26aa")
            alert_lines.append(
                f"{icon} <b>{_esc(a.get('title', 'Alert'))}:</b> {_esc(a.get('detail', ''))}"
            )
        parts.append(f"<b>Active Alerts</b>\n" + "\n".join(alert_lines))
        parts.append(_DIV)

    # 30-day averages
    avg = data.get("engagement_30d_avg", [])
    if avg:
        a = avg[0] if isinstance(avg, list) else avg
        parts.append(
            f"<i>\U0001f4ca 30-day avg: <b>{a.get('avg_score', 0)}</b> engagement | "
            f"<b>{a.get('avg_journals', 0)}</b> journals/day | "
            f"<b>{a.get('avg_completed', 0)}</b> actions/day | "
            f"<b>{a.get('days_tracked', 0)}</b> days tracked</i>"
        )

    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 13. Dashboard (ICOR heatmap)
# ---------------------------------------------------------------------------

def format_dashboard(icor_data: dict, projects: list, actions: list) -> FormatResult:
    """Format ICOR heatmap dashboard as Telegram HTML.

    Args:
        icor_data: Dimension name -> list of key elements with scores.
        projects: List of active projects.
        actions: List of pending actions.
    """
    parts = ["<b>\U0001f3af ICOR Dashboard</b>"]

    for dimension, elements in icor_data.items():
        element_lines = []
        for el in elements:
            score = el.get("attention_score", 0)
            if score >= 7:
                indicator = "\U0001f7e2"
            elif score >= 4:
                indicator = "\U0001f7e1"
            else:
                indicator = "\U0001f534"
            element_lines.append(f"  {indicator} {_esc(el['name'])} ({score:.1f})")

        parts.append(f"\n<b>{_esc(dimension)}</b>\n" + "\n".join(element_lines))

    parts.append(_DIV)

    # Active projects
    if projects:
        proj_lines = "\n".join(
            f"\u2022 <b>{_esc(p['name'])}</b> ({_esc(p.get('status', 'N/A'))})"
            for p in projects[:10]
        )
        parts.append(f"<b>Active Projects ({len(projects)}):</b>\n{proj_lines}")

    # Pending actions count
    if actions:
        parts.append(f"\n<i>Pending actions: {len(actions)}</i>")

    parts.append(f"\n<i>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 14. Cost Report
# ---------------------------------------------------------------------------

def format_cost_report(data: dict, days: int = 30) -> FormatResult:
    """Format API cost report as Telegram HTML.

    Expected data keys:
        - daily: list[dict] with date, calls, daily_cost, input_tokens, output_tokens
        - by_caller: list[dict] with caller, calls, total_cost, avg_input, avg_output
        - by_model: list[dict] with model, calls, total_cost
    """
    parts = [f"<b>\U0001f4b0 API Cost Report (Last {days} Days)</b>"]

    daily = data.get("daily", [])
    by_caller = data.get("by_caller", [])
    by_model = data.get("by_model", [])

    # Summary stats
    total_cost = sum(r.get("daily_cost", 0) or 0 for r in daily)
    total_calls = sum(r.get("calls", 0) or 0 for r in daily)
    avg_cost = total_cost / total_calls if total_calls else 0

    parts.append(
        f"\n<b>Total cost:</b> ${total_cost:.4f} | "
        f"<b>Total calls:</b> {total_calls} | "
        f"<b>Avg cost/call:</b> ${avg_cost:.4f}"
    )

    parts.append(_DIV)

    # Daily breakdown (last 7 days)
    if daily:
        lines = []
        for row in daily[:7]:
            date = _esc(row.get("date", "?"))
            calls = row.get("calls", 0)
            cost = row.get("daily_cost", 0) or 0
            inp = row.get("input_tokens", 0) or 0
            out = row.get("output_tokens", 0) or 0
            lines.append(
                f"<code>{date}</code> \u2014 {calls} calls, ${cost:.4f}, {inp:,} in / {out:,} out"
            )
        parts.append(f"<b>Daily Breakdown</b>\n" + "\n".join(lines))
    else:
        parts.append(f"<b>Daily Breakdown</b>\nNo API calls in this period.")

    parts.append(_DIV)

    # Top callers
    if by_caller:
        lines = []
        for row in by_caller[:10]:
            caller = _esc(row.get("caller", "?"))
            calls = row.get("calls", 0)
            cost = row.get("total_cost", 0) or 0
            avg_in = int(row.get("avg_input", 0) or 0)
            avg_out = int(row.get("avg_output", 0) or 0)
            lines.append(
                f"  <code>{caller}</code> \u2014 {calls} calls, "
                f"${cost:.4f} (avg {avg_in:,} in / {avg_out:,} out)"
            )
        parts.append(f"<b>Top Callers</b>\n" + "\n".join(lines))

    parts.append(_DIV)

    # Model breakdown
    if by_model:
        lines = []
        for row in by_model:
            model = _esc(row.get("model", "?"))
            calls = row.get("calls", 0)
            cost = row.get("total_cost", 0) or 0
            lines.append(f"  <code>{model}</code> \u2014 {calls} calls, ${cost:.4f}")
        parts.append(f"<b>Model Breakdown</b>\n" + "\n".join(lines))

    parts.append(f"\n<i>Generated at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# 15. Error Message
# ---------------------------------------------------------------------------

def format_error(message: str) -> FormatResult:
    """Format error message as Telegram HTML."""
    return f"\u274c <b>Error</b>\n{_esc(message)}", None


# ---------------------------------------------------------------------------
# 16. Sync Results
# ---------------------------------------------------------------------------

def format_sync_report(result) -> FormatResult:
    """Format Notion sync report as Telegram HTML.

    Args:
        result: SyncResult dataclass with sync counts, errors, warnings.
    """
    has_errors = bool(result.errors)
    status_text = "Completed with errors" if has_errors else "Completed successfully"
    status_icon = "\u26a0\ufe0f" if has_errors else "\u2705"

    parts = [f"<b>{status_icon} Notion Sync {_esc(status_text)}</b>"]

    # Sync counts
    counts = []
    if result.tasks_pushed:
        counts.append(f"\u2b06\ufe0f Tasks pushed: {result.tasks_pushed}")
    if result.tasks_status_synced:
        counts.append(f"\U0001f504 Task statuses synced: {result.tasks_status_synced}")
    if result.projects_pulled:
        counts.append(f"\u2b07\ufe0f Projects pulled: {result.projects_pulled}")
    if result.goals_pulled:
        counts.append(f"\u2b07\ufe0f Goals pulled: {result.goals_pulled}")
    if result.tags_synced:
        counts.append(f"\U0001f3f7\ufe0f Tags synced: {result.tags_synced}")
    if result.notes_pushed:
        counts.append(f"\u2b06\ufe0f Journal notes pushed: {result.notes_pushed}")
    if result.concepts_pushed:
        counts.append(f"\u2b06\ufe0f Concepts pushed: {result.concepts_pushed}")
    if result.people_synced:
        counts.append(f"\U0001f465 People synced: {result.people_synced}")
    if result.ai_calls:
        counts.append(f"\U0001f9e0 AI decisions: {result.ai_calls}")

    if counts:
        parts.append(f"\n<b>Sync Summary</b>\n" + "\n".join(counts))
    else:
        parts.append("\nNo changes needed \u2014 everything is in sync.")

    # Errors
    if result.errors:
        parts.append(_DIV)
        error_text = "\n".join(f"\u274c {_esc(e)}" for e in result.errors[:10])
        if len(result.errors) > 10:
            error_text += f"\n<i>...and {len(result.errors) - 10} more errors</i>"
        parts.append(f"<b>Errors ({len(result.errors)})</b>\n{error_text}")

    # Warnings
    if result.warnings:
        parts.append(_DIV)
        warning_text = "\n".join(f"\u26a0\ufe0f {_esc(w)}" for w in result.warnings[:10])
        if len(result.warnings) > 10:
            warning_text += f"\n<i>...and {len(result.warnings) - 10} more warnings</i>"
        parts.append(f"<b>Warnings ({len(result.warnings)})</b>\n{warning_text}")

    parts.append(
        f"\n<i>{status_icon} Sync completed at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
    )
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def format_help() -> FormatResult:
    """Format help listing all commands as Telegram HTML."""
    commands = [
        ("/brain-today", "Morning review + daily note"),
        ("/brain-close", "Evening review + journal index"),
        ("/brain-schedule", "Energy-aware weekly planning"),
        ("/brain-drift", "Goal vs. journal alignment analysis"),
        ("/brain-ideas", "Actionable idea generation from vault"),
        ("/brain-emerge", "Surface hidden patterns from notes"),
        ("/brain-ghost", "Digital twin answers a question"),
        ("/brain-trace", "Track concept evolution over time"),
        ("/brain-connect", "Find connections between two domains"),
        ("/brain-challenge", "Red-team a belief with counter-evidence"),
        ("/brain-graduate", "Promote journal themes to concepts"),
        ("/brain-projects", "Active project dashboard"),
        ("/brain-resources", "Knowledge base catalog"),
        ("/brain-review", "GTD weekly review"),
        ("/brain-find", "Semantic vault search"),
        ("/brain-cost", "API token usage &amp; cost dashboard"),
        ("/brain-status", "Quick SQLite status dashboard"),
        ("/brain-sync", "Bidirectional Notion sync"),
        ("/brain-context", "Load session context"),
        ("/brain-maintain", "Graph health check"),
        ("/brain-help", "This help message"),
    ]

    lines = [f"<code>{cmd}</code> \u2014 {desc}" for cmd, desc in commands]

    parts = [
        "<b>\U0001f9e0 Second Brain Commands</b>",
        "\n" + "\n".join(lines),
        _DIV,
        "<b>Tips:</b>\n"
        "\u2022 Most commands accept optional text input (e.g. <code>/brain-trace mindfulness</code>)\n"
        "\u2022 <code>/brain-sync tasks,projects</code> syncs only specific entity types\n"
        "\u2022 Captures in inbox are auto-classified and routed",
        f"\n<i>Second Brain v1.0 | {datetime.now().strftime('%Y-%m-%d')}</i>",
    ]
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

def format_health_check(checks: dict) -> FormatResult:
    """Format startup health check results as Telegram HTML."""
    parts = ["<b>\U0001f3e5 Bot Startup Health Check</b>", _DIV]

    for name, status in checks.items():
        if "FAIL" in status:
            emoji = "\u274c"
        elif "WARN" in status:
            emoji = "\u26a0\ufe0f"
        else:
            emoji = "\u2705"
        parts.append(f"{emoji} <b>{_esc(name)}:</b> {_esc(status)}")

    parts.append(f"\n<i>Started at {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")
    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# Fading Memories
# ---------------------------------------------------------------------------

def format_fading_memories(fading_items: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    """Format fading memories section for the evening prompt.

    Args:
        fading_items: List of dicts with keys: title, days_old, edge_count, file_path

    Returns:
        (html_text, inline_keyboard) tuple
    """
    if not fading_items:
        return "", None

    lines = [
        f"\n{_DIV}",
        "<b>Fading Memories</b>",
        "These haven't been revisited in a while:\n",
    ]
    for item in fading_items[:3]:
        title = _esc(item.get("title", "?"))
        days = item.get("days_old", 0)
        edges = item.get("edge_count", 0)
        lines.append(f"  \u2022 <b>{title}</b> \u2014 {days}d, {edges} connections")

    lines.append("\n<i>A quick review keeps knowledge fresh.</i>")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "\U0001f50d Review Top",
            callback_data=_cb({"a": "review_fading"}),
        ),
        InlineKeyboardButton(
            "\u2705 Dismiss",
            callback_data=_cb({"a": "dismiss"}),
        ),
    ]])

    return "\n".join(lines), kb
