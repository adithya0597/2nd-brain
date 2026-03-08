"""Build the Block Kit view payload for the Slack App Home tab."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta

from core.db_connection import get_connection

logger = logging.getLogger(__name__)

# ICOR dimensions in display order
_ICOR_DIMENSIONS = [
    "Health & Vitality",
    "Wealth & Finance",
    "Relationships",
    "Mind & Growth",
    "Purpose & Impact",
    "Systems & Environment",
]


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _header(text: str) -> dict:
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


def _relative_time(dt_str: str) -> str:
    """Convert a datetime string to a relative time like '2h', '3d'."""
    try:
        dt = datetime.fromisoformat(dt_str)
        delta = datetime.now() - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except (ValueError, TypeError):
        return "?"


def _build_brain_level_section(db_path=None) -> list[dict]:
    """Build the Brain Level gauge section."""
    blocks = [_header("BRAIN LEVEL")]

    try:
        with get_connection(db_path=db_path) as conn:
            row = conn.execute(
                """
                SELECT level, consistency_score, breadth_score, depth_score,
                       growth_score, momentum_score, days_active, period
                FROM brain_level
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ).fetchone()
    except Exception:
        logger.debug("Could not query brain_level", exc_info=True)
        row = None

    if not row:
        blocks.append(_section("Brain Level: Computing..."))
        return blocks

    level, consistency, breadth, depth, growth, momentum, days_active, period = row
    filled = "\u2588" * level
    empty = "\u2591" * (10 - level)
    bar = f"Level {level}/10  [{filled}{empty}]"
    components = (
        f"C:{consistency:.1f} B:{breadth:.1f} D:{depth:.1f} "
        f"G:{growth:.1f} M:{momentum:.1f}"
    )
    info = f"Days active: {days_active} | Period: {period}"
    blocks.append(_section(f"{bar}\n{components}\n{info}"))

    return blocks


def _build_dimension_momentum_section(db_path=None) -> list[dict]:
    """Build the Dimension Momentum heatmap section."""
    blocks = [_header("DIMENSION MOMENTUM")]

    _MOMENTUM_INDICATORS = {
        "hot": "\u25b2\u25b2",
        "warm": "\u25b2 ",
        "cold": "\u25bd ",
        "frozen": "\u25bd\u25bd",
    }
    _TREND_ARROWS = {
        "rising": "\u2191",
        "stable": "\u2192",
        "declining": "\u2193",
    }

    try:
        with get_connection(db_path=db_path) as conn:
            # Get the most recent date that has dimension_signals
            date_row = conn.execute(
                "SELECT MAX(date) FROM dimension_signals"
            ).fetchone()
            if not date_row or not date_row[0]:
                blocks.append(_section("Dimension signals: Computing..."))
                return blocks

            latest_date = date_row[0]
            rows = conn.execute(
                """
                SELECT dimension, momentum, trend
                FROM dimension_signals
                WHERE date = ?
                ORDER BY dimension
                """,
                (latest_date,),
            ).fetchall()
    except Exception:
        logger.debug("Could not query dimension_signals", exc_info=True)
        rows = []

    if not rows:
        blocks.append(_section("Dimension signals: Computing..."))
        return blocks

    indicators = []
    for dimension, momentum, trend in rows:
        short_name = dimension.split(" & ")[0] if " & " in dimension else dimension
        ind = _MOMENTUM_INDICATORS.get(momentum, "  ")
        arrow = _TREND_ARROWS.get(trend, "\u2192")
        indicators.append(f"{ind} {short_name}: {momentum} {arrow}")

    # Two rows of 3 (or fewer if not all 6 dimensions present)
    row1 = "  ".join(indicators[:3])
    row2 = "  ".join(indicators[3:6])
    text = f"{row1}\n{row2}" if row2 else row1
    blocks.append(_section(text))

    return blocks


def _build_active_alerts_section(db_path=None) -> list[dict]:
    """Build the active alerts section with Dismiss buttons."""
    _SEVERITY_INDICATORS = {
        "critical": "!!",
        "warning": "!",
        "info": "i",
    }

    try:
        with get_connection(db_path=db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, severity, title
                FROM alerts
                WHERE status = 'active'
                ORDER BY
                    CASE WHEN severity = 'critical' THEN 1
                         WHEN severity = 'warning' THEN 2
                         ELSE 3 END,
                    created_at DESC
                LIMIT 5
                """
            ).fetchall()
    except Exception:
        logger.debug("Could not query alerts", exc_info=True)
        rows = []

    if not rows:
        return []

    blocks = [_header("ALERTS")]

    for alert_id, severity, title in rows:
        sev_ind = _SEVERITY_INDICATORS.get(severity, "i")
        blocks.append(_section(f"[{sev_ind}] {title}"))
        blocks.append({
            "type": "actions",
            "elements": [
                _button("Dismiss", "app_home_dismiss_alert", str(alert_id)),
            ],
        })

    return blocks


def _build_engagement_trend_section(db_path=None) -> list[dict]:
    """Build the 7-day engagement trend sparkline section."""
    blocks = [_header("7-DAY ENGAGEMENT")]

    try:
        with get_connection(db_path=db_path) as conn:
            rows = conn.execute(
                """
                SELECT date, engagement_score
                FROM engagement_daily
                ORDER BY date DESC
                LIMIT 7
                """
            ).fetchall()
    except Exception:
        logger.debug("Could not query engagement_daily", exc_info=True)
        rows = []

    if not rows:
        blocks.append(_section("Engagement trend: Computing..."))
        return blocks

    # Reverse to chronological order (ASC)
    rows = list(reversed(rows))

    _DAY_ABBREVS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines = []
    total_score = 0.0
    for date_str, score in rows:
        total_score += score
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_abbr = _DAY_ABBREVS[dt.weekday()]
        except (ValueError, IndexError):
            day_abbr = "???"
        bar_len = int(round(score / 10.0 * 10))
        bar_len = max(0, min(10, bar_len))
        filled = "\u2588" * bar_len
        empty = "\u2591" * (10 - bar_len)
        lines.append(f"{day_abbr}  {filled}{empty}  {score:.1f}")

    avg = total_score / len(rows)
    lines.append(f"Avg: {avg:.1f}/10")

    blocks.append(_section("\n".join(lines)))

    return blocks


def _build_dashboard_summary(db_path=None) -> list[dict]:
    """Build the ICOR heatmap dashboard section."""
    blocks = [_header("SECOND BRAIN DASHBOARD")]

    dim_scores = {}
    pending_count = 0
    journaled_today = False

    try:
        with get_connection(db_path=db_path) as conn:
            # Get attention scores per dimension
            rows = conn.execute(
                """
                SELECT h.name, COALESCE(MAX(a.attention_score), 0) as score
                FROM icor_hierarchy h
                LEFT JOIN attention_indicators a ON a.icor_element_id = h.id
                WHERE h.level = 'dimension'
                GROUP BY h.name
                """
            ).fetchall()
            for name, score in rows:
                dim_scores[name] = score

            # Pending action count
            row = conn.execute(
                "SELECT COUNT(*) FROM action_items WHERE status = 'pending'"
            ).fetchone()
            pending_count = row[0] if row else 0

            # Check if journaled today
            today = datetime.now().strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COUNT(*) FROM journal_entries WHERE date = ?", (today,)
            ).fetchone()
            journaled_today = (row[0] > 0) if row else False
    except Exception:
        logger.debug("Could not query DB for dashboard summary", exc_info=True)

    # Build heatmap line
    indicators = []
    for dim in _ICOR_DIMENSIONS:
        score = dim_scores.get(dim, 0)
        dot = "\u25cf" if score > 2 else "\u25cb"  # filled vs empty circle
        short_name = dim.split(" & ")[0] if " & " in dim else dim
        indicators.append(f"{dot} {short_name}")

    # Two rows of 3
    row1 = "  ".join(indicators[:3])
    row2 = "  ".join(indicators[3:])
    journal_str = "Yes" if journaled_today else "No"
    summary = f"{row1}\n{row2}\nPending: {pending_count} | Journaled: {journal_str}"
    blocks.append(_section(summary))

    return blocks


def _build_quick_actions() -> list[dict]:
    """Build the quick action buttons section."""
    blocks = [_divider(), _section("*QUICK ACTIONS*")]

    # Row 1
    blocks.append({
        "type": "actions",
        "elements": [
            _button("Morning Briefing", "app_home_morning_briefing", "morning", "primary"),
            _button("Evening Review", "app_home_evening_review", "evening"),
            _button("Search Vault", "app_home_search_vault", "search"),
        ],
    })

    # Row 2
    blocks.append({
        "type": "actions",
        "elements": [
            _button("Sync Notion", "app_home_sync_notion", "sync"),
            _button("Weekly Review", "app_home_weekly_review", "review"),
            _button("Status", "app_home_brain_status", "status"),
        ],
    })

    return blocks


def _build_recent_captures(limit_per_dim: int = 3, db_path=None) -> list[dict]:
    """Build the recent captures section, grouped by dimension."""
    try:
        with get_connection(db_path=db_path) as conn:
            rows = conn.execute(
                """
                SELECT message_text, dimensions_json, created_at
                FROM captures_log
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
    except Exception:
        logger.debug("Could not query captures_log", exc_info=True)
        rows = []

    if not rows:
        return []

    blocks = [_divider(), _section("*RECENT CAPTURES*")]

    # Group by dimension
    by_dim: dict[str, list[tuple[str, str]]] = {}
    for text, dims_json, created_at in rows:
        try:
            dims = json.loads(dims_json) if dims_json else []
        except (json.JSONDecodeError, TypeError):
            dims = []
        if not dims:
            dims = ["Uncategorized"]
        for dim in dims:
            if dim not in by_dim:
                by_dim[dim] = []
            if len(by_dim[dim]) < limit_per_dim:
                by_dim[dim].append((text, created_at))

    for dim, captures in by_dim.items():
        lines = [f"*{dim}* ({len(captures)})"]
        for text, created_at in captures:
            rel = _relative_time(created_at)
            truncated = text[:80] + "..." if len(text) > 80 else text
            lines.append(f"  \u00b7 \"{truncated}\" ({rel})")
        blocks.append(_section("\n".join(lines)))

    return blocks


def _build_pending_actions(limit: int = 5, db_path=None) -> list[dict]:
    """Build the pending actions section with Complete/Snooze buttons."""
    try:
        with get_connection(db_path=db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, description, icor_element, source_date
                FROM action_items
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except Exception:
        logger.debug("Could not query action_items", exc_info=True)
        rows = []

    if not rows:
        return []

    blocks = [_divider(), _section("*PENDING ACTIONS*")]

    for row_id, description, icor_element, source_date in rows:
        action_id = str(row_id)
        text = f"\u00b7 {description}"
        if icor_element:
            text += f" _({icor_element})_"
        blocks.append(_section(text))
        blocks.append({
            "type": "actions",
            "elements": [
                _button("Complete", "app_home_complete", action_id, "primary"),
                _button("Snooze", "app_home_snooze", action_id),
            ],
        })

    return blocks


def build_app_home_view(user_id: str, db_path=None) -> dict:
    """Build the full App Home view payload for views.publish()."""
    blocks = []

    # 1. Brain Level
    blocks.extend(_build_brain_level_section(db_path=db_path))
    # 2. Dimension Momentum
    blocks.extend(_build_dimension_momentum_section(db_path=db_path))
    # 3. Dashboard Summary
    blocks.extend(_build_dashboard_summary(db_path=db_path))
    # 4. Alerts
    blocks.extend(_build_active_alerts_section(db_path=db_path))
    # 5. Quick Actions
    blocks.extend(_build_quick_actions())
    # 6. Engagement Trend
    blocks.extend(_build_engagement_trend_section(db_path=db_path))
    # 7. Recent Captures
    blocks.extend(_build_recent_captures(db_path=db_path))
    # 8. Pending Actions
    blocks.extend(_build_pending_actions(db_path=db_path))

    # 9. Footer
    blocks.append(_divider())
    blocks.append(_context(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))

    return {"type": "home", "blocks": blocks}
