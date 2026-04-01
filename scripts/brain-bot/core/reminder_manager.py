"""Reminder scheduling and persistence for action items."""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.db_ops import execute, query

logger = logging.getLogger(__name__)
CST = ZoneInfo("America/Chicago")


async def schedule_reminder(job_queue, action_id: int, title: str, due_date_str: str):
    """Schedule a Telegram reminder for a task.

    Schedules for 7am CST on the due date (or 5 minutes from now if due today
    and already past 7am). Skips tasks already overdue.
    """
    try:
        due = date.fromisoformat(due_date_str)
        today = date.today()

        if due < today:
            return  # Already overdue, morning briefing handles it

        # Reminder fires at 7am on the due date
        remind_dt = datetime.combine(due, time(7, 0), tzinfo=CST)
        now = datetime.now(CST)

        if remind_dt <= now:
            # Due today and past 7am -- remind in 5 minutes
            remind_dt = now + timedelta(minutes=5)

        # Persist to DB (store as UTC for consistent SQLite comparison)
        remind_utc = remind_dt.astimezone(ZoneInfo("UTC"))
        await execute(
            "INSERT INTO reminders (action_item_id, remind_at, status) VALUES (?, ?, 'pending')",
            (action_id, remind_utc.strftime("%Y-%m-%d %H:%M:%S")),
        )

        # Schedule with PTB JobQueue
        job_queue.run_once(
            _send_reminder,
            when=remind_dt,
            data={"action_id": action_id, "title": title, "due_date": due_date_str},
            name=f"reminder_{action_id}",
        )

        logger.info("Scheduled reminder for action %d at %s", action_id, remind_dt)

    except Exception:
        logger.exception("Failed to schedule reminder for action %d", action_id)


async def _send_reminder(context):
    """Send a reminder message to the brain-actions topic."""
    data = context.job.data
    title = data["title"]
    due_date = data["due_date"]
    action_id = data["action_id"]

    try:
        import config
        from core.message_utils import send_long_message

        topic_id = config.TOPICS.get("brain-actions")
        text = (
            f"\u23f0 <b>Reminder:</b> {title}\n"
            f"\U0001f4c5 Due: {due_date}\n\n"
            f"<i>Complete this task or snooze it.</i>"
        )

        await send_long_message(
            context.bot,
            chat_id=config.GROUP_CHAT_ID,
            text=text,
            topic_id=topic_id,
        )

        # Mark reminder as sent
        await execute(
            "UPDATE reminders SET status = 'sent' WHERE action_item_id = ?",
            (action_id,),
        )

        logger.info("Sent reminder for action %d", action_id)

    except Exception:
        logger.exception("Failed to send reminder for action %d", action_id)


async def reload_pending_reminders(job_queue):
    """Reload pending reminders from SQLite on bot startup.

    Called from app.py post_init to restore reminders that were scheduled
    before a restart.
    """
    try:
        rows = await query(
            """SELECT r.id, r.action_item_id, r.remind_at, a.description
               FROM reminders r
               JOIN action_items a ON a.id = r.action_item_id
               WHERE r.status = 'pending' AND r.remind_at > datetime('now')""",
        )

        if not rows:
            return

        count = 0
        for row in rows:
            remind_dt = datetime.fromisoformat(row["remind_at"])
            if remind_dt.tzinfo is None:
                remind_dt = remind_dt.replace(tzinfo=CST)

            now = datetime.now(CST)
            if remind_dt <= now:
                # Missed reminder -- fire in 30 seconds
                remind_dt = now + timedelta(seconds=30)

            job_queue.run_once(
                _send_reminder,
                when=remind_dt,
                data={
                    "action_id": row["action_item_id"],
                    "title": row["description"],
                    "due_date": remind_dt.date().isoformat(),
                },
                name=f"reminder_{row['action_item_id']}",
            )
            count += 1

        logger.info("Reloaded %d pending reminders from database", count)

    except Exception:
        logger.exception("Failed to reload reminders")
