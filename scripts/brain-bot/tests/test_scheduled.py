"""Tests for handlers/scheduled.py — scheduled job functions."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRAIN_BOT_DIR = Path(__file__).parent.parent
if str(BRAIN_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_BOT_DIR))

sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("telegram", MagicMock())
sys.modules.setdefault("telegram.ext", MagicMock())

# Ensure config attributes are set before import
cfg = sys.modules["config"]
cfg.DB_PATH = Path("/tmp/test.db")
cfg.VAULT_PATH = Path("/tmp/vault")
cfg.GROUP_CHAT_ID = -100123
cfg.TOPICS = {"brain-daily": 2, "brain-insights": 3, "brain-dashboard": 4}
cfg.DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness"],
    "Systems & Environment": ["system", "automate"],
}
cfg.NOTION_TOKEN = ""
cfg.NOTION_COLLECTIONS = {}
cfg.NOTION_REGISTRY_PATH = Path("/tmp/registry.json")
cfg.BOUNCER_TIMEOUT_MINUTES = 15
cfg.load_dynamic_keywords = MagicMock(return_value={})

from handlers.scheduled import (
    _record_job_run,
    _notify_job_failure,
    _should_run_biweekly,
    _send_to_topic,
    _call_claude,
    job_morning_briefing,
    job_evening_prompt,
    job_dashboard_refresh,
    job_notion_sync,
    job_drift_report,
    job_emerge_biweekly,
    job_weekly_project_summary,
    job_monthly_resource_digest,
    job_vault_reindex,
    job_keyword_expansion,
    job_weekly_review,
    job_db_backup,
    job_daily_engagement,
    job_dimension_signals,
    job_weekly_brain_level,
    job_resolve_pending_captures,
    job_rolling_memo,
    job_graph_maintenance,
    job_graduation_proposals,
    job_system_health_check,
    register_jobs,
)


@pytest.fixture
def mock_cb_context():
    """Mock CallbackContext with a mock bot."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestRecordJobRun:
    def test_record_success(self):
        mock_conn = MagicMock()
        with patch("core.db_connection.get_connection", return_value=mock_conn):
            _record_job_run("test_job")
        mock_conn.__enter__().execute.assert_called_once()

    def test_record_failure_logs_warning(self):
        with patch("core.db_connection.get_connection", side_effect=Exception("db")):
            # Should not raise
            _record_job_run("test_job")


class TestNotifyJobFailure:
    @pytest.mark.asyncio
    async def test_sends_to_daily(self):
        bot = MagicMock()
        with patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock) as mock_send:
            await _notify_job_failure(bot, "morning_briefing", RuntimeError("timeout"))
        mock_send.assert_awaited_once()
        call_args = mock_send.call_args
        assert "morning_briefing" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_failure_in_notification_does_not_raise(self):
        bot = MagicMock()
        with patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock, side_effect=Exception("send fail")):
            await _notify_job_failure(bot, "test", RuntimeError("x"))


class TestShouldRunBiweekly:
    def test_no_previous_run(self):
        mock_conn = MagicMock()
        mock_conn.__enter__().execute.return_value.fetchone.return_value = None
        with patch("handlers.scheduled.get_connection", return_value=mock_conn):
            assert _should_run_biweekly("emerge") is True

    def test_recent_run_skips(self):
        from datetime import datetime
        mock_conn = MagicMock()
        mock_conn.__enter__().execute.return_value.fetchone.return_value = (
            datetime.now().isoformat(),
        )
        with patch("handlers.scheduled.get_connection", return_value=mock_conn):
            assert _should_run_biweekly("emerge") is False

    def test_old_run_allows(self):
        from datetime import datetime, timedelta
        old_date = (datetime.now() - timedelta(days=15)).isoformat()
        mock_conn = MagicMock()
        mock_conn.__enter__().execute.return_value.fetchone.return_value = (old_date,)
        with patch("handlers.scheduled.get_connection", return_value=mock_conn):
            assert _should_run_biweekly("emerge") is True

    def test_db_error_returns_true(self):
        with patch("handlers.scheduled.get_connection", side_effect=Exception("db")):
            assert _should_run_biweekly("emerge") is True


class TestSendToTopic:
    @pytest.mark.asyncio
    async def test_sends_to_configured_topic(self):
        bot = MagicMock()
        with patch("handlers.scheduled.send_long_message", new_callable=AsyncMock, return_value="ok") as mock_send:
            result = await _send_to_topic(bot, "brain-daily", "Hello")
        mock_send.assert_awaited_once()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_unconfigured_topic_skips(self):
        bot = MagicMock()
        with patch("handlers.scheduled.send_long_message", new_callable=AsyncMock) as mock_send:
            with patch("handlers.scheduled.TOPICS", {}):
                result = await _send_to_topic(bot, "brain-nonexistent", "Hello")
        mock_send.assert_not_awaited()
        assert result is None


# ---------------------------------------------------------------------------
# _call_claude
# ---------------------------------------------------------------------------

class TestCallClaude:
    @pytest.mark.asyncio
    async def test_call_claude_returns_text(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="AI response")]

        mock_ai = MagicMock()
        mock_ai.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("handlers.scheduled.gather_command_context", new_callable=AsyncMock, return_value={}),
            patch("handlers.scheduled.load_system_context", return_value="system"),
            patch("handlers.scheduled.load_command_prompt", return_value="prompt"),
            patch("handlers.scheduled.build_claude_messages", return_value=[]),
            patch("handlers.scheduled.get_ai_client", return_value=mock_ai),
            patch("handlers.scheduled.get_ai_model", return_value="test-model"),
        ):
            result = await _call_claude("today")

        assert result == "AI response"

    @pytest.mark.asyncio
    async def test_call_claude_no_client_raises(self):
        with (
            patch("handlers.scheduled.gather_command_context", new_callable=AsyncMock, return_value={}),
            patch("handlers.scheduled.load_system_context", return_value="system"),
            patch("handlers.scheduled.load_command_prompt", return_value="prompt"),
            patch("handlers.scheduled.build_claude_messages", return_value=[]),
            patch("handlers.scheduled.get_ai_client", return_value=None),
            patch("handlers.scheduled.get_ai_model", return_value="test-model"),
        ):
            with pytest.raises(RuntimeError, match="AI client not initialized"):
                await _call_claude("today")


# ---------------------------------------------------------------------------
# Job Functions
# ---------------------------------------------------------------------------

class TestJobMorningBriefing:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Good morning!"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_morning_briefing(mock_cb_context)

    @pytest.mark.asyncio
    async def test_failure_notifies(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, side_effect=Exception("API fail")),
            patch("handlers.scheduled._notify_job_failure", new_callable=AsyncMock) as mock_notify,
        ):
            await job_morning_briefing(mock_cb_context)
        mock_notify.assert_awaited_once()


class TestJobEveningPrompt:
    @pytest.mark.asyncio
    async def test_success_no_fading(self, mock_cb_context):
        with (
            patch("handlers.scheduled.get_pending_actions", new_callable=AsyncMock, return_value=[{"id": 1}]),
            patch("handlers.scheduled.get_recent_journal", new_callable=AsyncMock, return_value=[]),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock) as mock_send,
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_evening_prompt(mock_cb_context)
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][2]
        assert "Evening Review" in text
        assert "Pending actions:" in text

    @pytest.mark.asyncio
    async def test_failure(self, mock_cb_context):
        with (
            patch("handlers.scheduled.get_pending_actions", new_callable=AsyncMock, side_effect=Exception("db fail")),
            patch("handlers.scheduled._notify_job_failure", new_callable=AsyncMock),
        ):
            await job_evening_prompt(mock_cb_context)


class TestJobDashboardRefresh:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        mock_attention = [
            {"dimension": "Health", "name": "Fitness", "attention_score": 7.0},
        ]
        with (
            patch("handlers.scheduled.compute_attention_scores", new_callable=AsyncMock, return_value=5),
            patch("handlers.scheduled.get_pending_actions", new_callable=AsyncMock, return_value=[]),
            patch("handlers.scheduled.get_attention_scores", new_callable=AsyncMock, return_value=mock_attention),
            patch("handlers.scheduled.get_neglected_elements", new_callable=AsyncMock, return_value=[]),
            patch("handlers.scheduled.format_dashboard", return_value=("<b>Dashboard</b>", None)),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_dashboard_refresh(mock_cb_context)


class TestJobNotionSync:
    @pytest.mark.asyncio
    async def test_skips_without_token(self, mock_cb_context):
        with patch("handlers.scheduled.NOTION_TOKEN", ""):
            await job_notion_sync(mock_cb_context)

    @pytest.mark.asyncio
    async def test_sync_with_errors_posts_report(self, mock_cb_context):
        mock_result = MagicMock()
        mock_result.errors = ["Some error"]
        mock_result.summary.return_value = "Sync done with errors"

        mock_notion = MagicMock()
        mock_notion.close = AsyncMock()

        mock_syncer = MagicMock()
        mock_syncer.run_full_sync = AsyncMock(return_value=mock_result)

        with (
            patch("handlers.scheduled.NOTION_TOKEN", "test-token"),
            patch("handlers.scheduled.NotionClientWrapper", return_value=mock_notion),
            patch("handlers.scheduled.NotionSync", return_value=mock_syncer),
            patch("handlers.scheduled.format_sync_report", return_value=("<b>Report</b>", None)),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock) as mock_send,
            patch("handlers.scheduled._record_job_run"),
            patch("handlers.scheduled.get_ai_client", return_value=None),
            patch("handlers.scheduled.get_ai_model", return_value="test"),
        ):
            await job_notion_sync(mock_cb_context)
        mock_send.assert_awaited_once()


class TestJobDriftReport:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Drift results"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_drift_report(mock_cb_context)


class TestJobEmergeBiweekly:
    @pytest.mark.asyncio
    async def test_skips_if_recent(self, mock_cb_context):
        with patch("handlers.scheduled._should_run_biweekly", return_value=False):
            await job_emerge_biweekly(mock_cb_context)

    @pytest.mark.asyncio
    async def test_runs_if_due(self, mock_cb_context):
        with (
            patch("handlers.scheduled._should_run_biweekly", return_value=True),
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Patterns"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_emerge_biweekly(mock_cb_context)


class TestJobWeeklyProjectSummary:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Projects"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_weekly_project_summary(mock_cb_context)


class TestJobMonthlyResourceDigest:
    @pytest.mark.asyncio
    async def test_skips_non_first_day(self, mock_cb_context):
        from datetime import datetime
        with patch("handlers.scheduled.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 15)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await job_monthly_resource_digest(mock_cb_context)

    @pytest.mark.asyncio
    async def test_runs_on_first(self, mock_cb_context):
        from datetime import datetime as real_dt
        with (
            patch("handlers.scheduled.datetime") as mock_dt,
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Resources"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            mock_dt.now.return_value = real_dt(2026, 4, 1)
            mock_dt.side_effect = lambda *a, **k: real_dt(*a, **k)
            await job_monthly_resource_digest(mock_cb_context)


class TestJobVaultReindex:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=50),
            patch("handlers.scheduled.index_vault", return_value=50),
            patch("handlers.scheduled.index_journal", return_value=10),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_vault_reindex(mock_cb_context)


class TestJobKeywordExpansion:
    @pytest.mark.asyncio
    async def test_skips_without_ai(self, mock_cb_context):
        with patch("handlers.scheduled.get_ai_client", return_value=None):
            await job_keyword_expansion(mock_cb_context)

    @pytest.mark.asyncio
    async def test_skips_no_corrections(self, mock_cb_context):
        mock_ai = MagicMock()
        with (
            patch("handlers.scheduled.get_ai_client", return_value=mock_ai),
            patch("handlers.scheduled.query", new_callable=AsyncMock, return_value=[]),
        ):
            await job_keyword_expansion(mock_cb_context)

    @pytest.mark.asyncio
    async def test_processes_corrections(self, mock_cb_context):
        corrections = [
            {"message_text": "gym today", "primary_dimension": "Systems", "user_correction": "Health & Vitality"},
        ]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"Health & Vitality": ["gym", "exercise"]}')]

        mock_ai = MagicMock()
        mock_ai.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("handlers.scheduled.get_ai_client", return_value=mock_ai),
            patch("handlers.scheduled.get_ai_model", return_value="test-model"),
            patch("handlers.scheduled.query", new_callable=AsyncMock, side_effect=[corrections, None, None]),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_keyword_expansion(mock_cb_context)


class TestJobWeeklyReview:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Review"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_weekly_review(mock_cb_context)


class TestJobDbBackup:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context, tmp_path):
        db_file = tmp_path / "brain.db"
        db_file.write_text("")

        with (
            patch("handlers.scheduled.DB_PATH", str(db_file)),
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_db_backup(mock_cb_context)


class TestJobDailyEngagement:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        mock_metrics = {"engagement_score": 5.5}
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=mock_metrics),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_daily_engagement(mock_cb_context)


class TestJobDimensionSignals:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=[{"dim": "Health"}]),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_dimension_signals(mock_cb_context)


class TestJobWeeklyBrainLevel:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value={"level": 7}),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_weekly_brain_level(mock_cb_context)


class TestJobResolvePendingCaptures:
    @pytest.mark.asyncio
    async def test_no_table(self, mock_cb_context):
        with patch("handlers.scheduled.query", new_callable=AsyncMock, return_value=[]):
            await job_resolve_pending_captures(mock_cb_context)

    @pytest.mark.asyncio
    async def test_with_pending_rows(self, mock_cb_context):
        table_check = [{"name": "pending_captures"}]
        pending_rows = [
            {"id": 1, "message_text": "test", "message_ts": "123", "primary_dimension": "Health",
             "chat_id": "-100", "bouncer_dm_ts": "456", "bouncer_dm_channel": "C1"},
        ]

        with (
            patch("handlers.scheduled.query", new_callable=AsyncMock, side_effect=[table_check, pending_rows]),
            patch("handlers.scheduled.execute", new_callable=AsyncMock),
            patch("handlers.capture.process_bouncer_resolution", new_callable=AsyncMock),
        ):
            await job_resolve_pending_captures(mock_cb_context)


class TestJobRollingMemo:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, return_value="Memo content"),
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=True),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_rolling_memo(mock_cb_context)

    @pytest.mark.asyncio
    async def test_failure_notifies(self, mock_cb_context):
        with (
            patch("handlers.scheduled._call_claude", new_callable=AsyncMock, side_effect=Exception("API fail")),
            patch("handlers.scheduled._notify_job_failure", new_callable=AsyncMock) as mock_notify,
        ):
            await job_rolling_memo(mock_cb_context)
        mock_notify.assert_awaited_once()


class TestJobGraphMaintenance:
    @pytest.mark.asyncio
    async def test_with_orphans(self, mock_cb_context):
        result = {
            "orphans": [{"title": "Old Note"}],
            "total_orphans": 1,
            "stale_concepts": [],
            "density": {"density": 0.05},
        }
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=result),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_graph_maintenance(mock_cb_context)

    @pytest.mark.asyncio
    async def test_no_orphans(self, mock_cb_context):
        result = {"orphans": [], "total_orphans": 0, "stale_concepts": [], "density": {"density": 0.1}}
        with (
            patch("handlers.scheduled.run_in_executor", new_callable=AsyncMock, return_value=result),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_graph_maintenance(mock_cb_context)


class TestJobGraduationProposals:
    @pytest.mark.asyncio
    async def test_no_candidates(self, mock_cb_context):
        mock_conn = MagicMock()
        with (
            patch("handlers.scheduled.get_connection", return_value=mock_conn),
            patch("handlers.scheduled.detect_graduation_candidates", new_callable=AsyncMock, return_value=[]),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_graduation_proposals(mock_cb_context)


class TestJobSystemHealthCheck:
    @pytest.mark.asyncio
    async def test_success(self, mock_cb_context):
        mock_conn = MagicMock()
        mock_conn.__enter__().execute.return_value.fetchall.return_value = [
            ("wikilink", 50), ("tag_shared", 20),
        ]
        mock_conn.__enter__().execute.return_value.fetchone.return_value = (100,)

        with (
            patch("handlers.scheduled.get_connection", return_value=mock_conn),
            patch("handlers.scheduled.get_ai_client", return_value=MagicMock()),
            patch("handlers.scheduled.get_ai_model", return_value="test-model"),
            patch("handlers.scheduled._detect_provider", return_value="anthropic"),
            patch("handlers.scheduled._send_to_topic", new_callable=AsyncMock),
            patch("handlers.scheduled._record_job_run"),
        ):
            await job_system_health_check(mock_cb_context)


# ---------------------------------------------------------------------------
# register_jobs
# ---------------------------------------------------------------------------

class TestRegisterJobs:
    def test_registers_all_jobs(self):
        job_queue = MagicMock()
        job_queue.jobs.return_value = []
        register_jobs(job_queue)

        # Should call run_daily and run_repeating multiple times
        assert job_queue.run_daily.call_count >= 10
        assert job_queue.run_repeating.call_count >= 1
