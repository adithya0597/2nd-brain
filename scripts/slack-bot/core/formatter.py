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

def format_capture_confirmation(text: str, dimension: str, channel: str) -> list[dict]:
    """Confirmation message after routing a capture."""
    return [
        _section(f":white_check_mark: *Captured and routed*"),
        _section(f"> {text[:200]}{'...' if len(text) > 200 else ''}"),
        _context(f"Dimension: {dimension} | Routed to: #{channel}"),
    ]


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

def format_error(message: str) -> list[dict]:
    """Error message block."""
    return [
        _section(f":x: *Error*\n{message}"),
    ]
