"""Build Telegram HTML dashboard views for the Second Brain bot.

Replaces the Slack Block Kit app_home_builder.py with HTML output
and InlineKeyboardMarkup for interactive buttons.
"""
import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.db_connection import get_connection
from core.formatter import _esc, _cb

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

_DIV = "\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"


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


# ---------------------------------------------------------------------------
# Section builders (return HTML strings)
# ---------------------------------------------------------------------------

def _build_brain_level_section(db_path=None) -> str:
    """Build the Brain Level gauge section."""
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
        return "<b>\U0001f9e0 BRAIN LEVEL</b>\nComputing..."

    level, consistency, breadth, depth, growth, momentum, days_active, period = row
    filled = "\u2588" * level
    empty = "\u2591" * (10 - level)
    bar = f"Level {level}/10  <code>{filled}{empty}</code>"
    components = (
        f"C:{consistency:.1f} B:{breadth:.1f} D:{depth:.1f} "
        f"G:{growth:.1f} M:{momentum:.1f}"
    )
    info = f"Days active: {days_active} | Period: {period}"
    return f"<b>\U0001f9e0 BRAIN LEVEL</b>\n{bar}\n{components}\n{info}"


def _build_dimension_momentum_section(db_path=None) -> str:
    """Build the Dimension Momentum heatmap section."""
    _MOMENTUM_INDICATORS = {
        "hot": "\U0001f525",
        "warm": "\u2600\ufe0f",
        "cold": "\u2744\ufe0f",
        "frozen": "\U0001f9ca",
    }
    _TREND_ARROWS = {
        "rising": "\u2191",
        "stable": "\u2192",
        "declining": "\u2193",
    }

    try:
        with get_connection(db_path=db_path) as conn:
            date_row = conn.execute(
                "SELECT MAX(date) FROM dimension_signals"
            ).fetchone()
            if not date_row or not date_row[0]:
                return "<b>DIMENSION MOMENTUM</b>\nComputing..."

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
        return "<b>DIMENSION MOMENTUM</b>\nComputing..."

    lines = []
    for dimension, momentum, trend in rows:
        short_name = dimension.split(" & ")[0] if " & " in dimension else dimension
        ind = _MOMENTUM_INDICATORS.get(momentum, "\u2753")
        arrow = _TREND_ARROWS.get(trend, "\u2192")
        lines.append(f"{ind} <b>{_esc(short_name)}:</b> {momentum} {arrow}")

    return "<b>DIMENSION MOMENTUM</b>\n" + "\n".join(lines)


def _build_active_alerts_section(db_path=None) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Build the active alerts section. Returns (html, keyboard_rows)."""
    _SEVERITY_INDICATORS = {
        "critical": "\U0001f534",
        "warning": "\U0001f7e1",
        "info": "\U0001f535",
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
        return "", []

    lines = ["<b>\u26a0\ufe0f ALERTS</b>"]
    keyboard_rows = []
    for alert_id, severity, title in rows:
        sev_ind = _SEVERITY_INDICATORS.get(severity, "\u26aa")
        lines.append(f"{sev_ind} {_esc(title)}")
        keyboard_rows.append([
            InlineKeyboardButton(
                f"Dismiss: {title[:20]}",
                callback_data=_cb({"a": "dismiss_alert", "id": alert_id}),
            )
        ])

    return "\n".join(lines), keyboard_rows


def _build_engagement_trend_section(db_path=None) -> str:
    """Build the 7-day engagement trend sparkline section."""
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
        return "<b>7-DAY ENGAGEMENT</b>\nComputing..."

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
        lines.append(f"<code>{day_abbr}  {filled}{empty}  {score:.1f}</code>")

    avg = total_score / len(rows)
    lines.append(f"Avg: {avg:.1f}/10")

    return "<b>7-DAY ENGAGEMENT</b>\n" + "\n".join(lines)


def _build_dashboard_summary(db_path=None) -> str:
    """Build the ICOR heatmap dashboard section."""
    dim_scores = {}
    pending_count = 0
    journaled_today = False

    try:
        with get_connection(db_path=db_path) as conn:
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

            row = conn.execute(
                "SELECT COUNT(*) FROM action_items WHERE status = 'pending'"
            ).fetchone()
            pending_count = row[0] if row else 0

            today = datetime.now().strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COUNT(*) FROM journal_entries WHERE date = ?", (today,)
            ).fetchone()
            journaled_today = (row[0] > 0) if row else False
    except Exception:
        logger.debug("Could not query DB for dashboard summary", exc_info=True)

    indicators = []
    for dim in _ICOR_DIMENSIONS:
        score = dim_scores.get(dim, 0)
        dot = "\U0001f7e2" if score > 2 else "\U0001f534"
        short_name = dim.split(" & ")[0] if " & " in dim else dim
        indicators.append(f"{dot} {short_name}")

    row1 = "  ".join(indicators[:3])
    row2 = "  ".join(indicators[3:])
    journal_str = "\u2705 Yes" if journaled_today else "\u274c No"
    return (
        f"<b>\U0001f3af SECOND BRAIN DASHBOARD</b>\n"
        f"{row1}\n{row2}\n"
        f"Pending: {pending_count} | Journaled: {journal_str}"
    )


def _build_recent_captures(limit_per_dim: int = 3, db_path=None) -> str:
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
        return ""

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

    parts = ["<b>RECENT CAPTURES</b>"]
    for dim, captures in by_dim.items():
        lines = [f"\n<b>{_esc(dim)}</b> ({len(captures)})"]
        for text, created_at in captures:
            rel = _relative_time(created_at)
            truncated = _esc(text[:80]) + "..." if len(text) > 80 else _esc(text)
            lines.append(f"  \u00b7 \"{truncated}\" ({rel})")
        parts.append("\n".join(lines))

    return "\n".join(parts)


def _build_pending_actions(limit: int = 5, db_path=None) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Build the pending actions section. Returns (html, keyboard_rows)."""
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
        return "", []

    lines = ["<b>PENDING ACTIONS</b>"]
    keyboard_rows = []
    for row_id, description, icor_element, source_date in rows:
        text = f"\u00b7 {_esc(description)}"
        if icor_element:
            text += f" <i>({_esc(icor_element)})</i>"
        lines.append(text)
        keyboard_rows.append([
            InlineKeyboardButton(
                "\u2705 Complete",
                callback_data=_cb({"a": "dash_complete", "id": row_id}),
            ),
            InlineKeyboardButton(
                "\u23f0 Snooze",
                callback_data=_cb({"a": "dash_snooze", "id": row_id}),
            ),
        ])

    return "\n".join(lines), keyboard_rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_dashboard_view(db_path=None) -> tuple[str, InlineKeyboardMarkup]:
    """Build the full dashboard view as HTML + keyboard.

    Returns:
        (html_text, InlineKeyboardMarkup) ready for send_long_message.
    """
    sections = []

    # 1. Brain Level
    sections.append(_build_brain_level_section(db_path=db_path))

    sections.append(_DIV)

    # 2. Dimension Momentum
    sections.append(_build_dimension_momentum_section(db_path=db_path))

    sections.append(_DIV)

    # 3. Dashboard Summary
    sections.append(_build_dashboard_summary(db_path=db_path))

    # 4. Alerts
    alerts_html, alert_buttons = _build_active_alerts_section(db_path=db_path)
    if alerts_html:
        sections.append(_DIV)
        sections.append(alerts_html)

    sections.append(_DIV)

    # 5. Engagement Trend
    sections.append(_build_engagement_trend_section(db_path=db_path))

    # 6. Recent Captures
    captures_html = _build_recent_captures(db_path=db_path)
    if captures_html:
        sections.append(_DIV)
        sections.append(captures_html)

    # 7. Pending Actions
    actions_html, action_buttons = _build_pending_actions(db_path=db_path)
    if actions_html:
        sections.append(_DIV)
        sections.append(actions_html)

    # Footer
    sections.append(_DIV)
    sections.append(f"<i>Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>")

    html = "\n".join(sections)

    # Build keyboard: quick actions + alert dismiss + action buttons
    keyboard_rows = [
        [
            InlineKeyboardButton("\u2600\ufe0f Today", callback_data=_cb({"cmd": "today"})),
            InlineKeyboardButton("\U0001f319 Close Day", callback_data=_cb({"cmd": "close"})),
        ],
        [
            InlineKeyboardButton("\U0001f9ed Drift", callback_data=_cb({"cmd": "drift"})),
            InlineKeyboardButton("\U0001f4a1 Ideas", callback_data=_cb({"cmd": "ideas"})),
        ],
        [
            InlineKeyboardButton("\U0001f50d Find", callback_data=_cb({"cmd": "find"})),
            InlineKeyboardButton("\U0001f504 Sync", callback_data=_cb({"cmd": "sync"})),
        ],
    ]
    keyboard_rows.extend(alert_buttons)
    keyboard_rows.extend(action_buttons)

    return html, InlineKeyboardMarkup(keyboard_rows)


def build_pinned_summary(db_path=None) -> str:
    """Build compact pinned message (<4096 chars): Brain Level + 6 dimensions.

    Returns:
        HTML string suitable for editing the pinned message.
    """
    parts = []

    # Brain Level (compact)
    try:
        with get_connection(db_path=db_path) as conn:
            row = conn.execute(
                "SELECT level FROM brain_level ORDER BY computed_at DESC LIMIT 1"
            ).fetchone()
    except Exception:
        row = None

    level = row[0] if row else 0
    filled = "\u2588" * level
    empty = "\u2591" * (10 - level)
    parts.append(f"\U0001f9e0 <b>Brain Level {level}/10</b>  <code>{filled}{empty}</code>")

    # Dimension momentum (compact)
    try:
        with get_connection(db_path=db_path) as conn:
            date_row = conn.execute("SELECT MAX(date) FROM dimension_signals").fetchone()
            if date_row and date_row[0]:
                rows = conn.execute(
                    "SELECT dimension, momentum, trend FROM dimension_signals WHERE date = ?",
                    (date_row[0],),
                ).fetchall()
            else:
                rows = []
    except Exception:
        rows = []

    _MOMENTUM_ICONS = {"hot": "\U0001f525", "warm": "\u2600\ufe0f", "cold": "\u2744\ufe0f", "frozen": "\U0001f9ca"}
    _TREND_ICONS = {"rising": "\u2191", "stable": "\u2192", "declining": "\u2193"}

    for dimension, momentum, trend in rows:
        short = dimension.split(" & ")[0] if " & " in dimension else dimension
        m_icon = _MOMENTUM_ICONS.get(momentum, "\u2753")
        t_icon = _TREND_ICONS.get(trend, "\u2192")
        parts.append(f"{m_icon} {short}: {momentum} {t_icon}")

    # Pending count + journal status
    try:
        with get_connection(db_path=db_path) as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM action_items WHERE status = 'pending'"
            ).fetchone()[0]
            today = datetime.now().strftime("%Y-%m-%d")
            journaled = conn.execute(
                "SELECT COUNT(*) FROM journal_entries WHERE date = ?", (today,)
            ).fetchone()[0] > 0
    except Exception:
        pending = 0
        journaled = False

    j_icon = "\u2705" if journaled else "\u274c"
    parts.append(f"\nPending: {pending} | Journaled: {j_icon}")
    parts.append(f"<i>{datetime.now().strftime('%H:%M')}</i>")

    return "\n".join(parts)
