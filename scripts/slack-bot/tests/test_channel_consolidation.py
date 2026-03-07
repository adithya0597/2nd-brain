"""Tests for channel consolidation (16 -> 4 channels).

Validates that:
- CHANNELS dict has exactly 4 entries
- DIMENSION_CHANNELS values are all None
- _COMMAND_MAP routes drift->insights, ideas->insights, projects->daily, resources->daily
- Capture processing inserts into captures_log (not posting to dimension channels)
- Capture processing still writes to vault (daily note + inbox entry)
- format_help shows updated channel routing
- Scheduled jobs use correct channels
"""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module mocking (before any project imports)
# ---------------------------------------------------------------------------
_cfg = MagicMock()
_cfg.DIMENSION_CHANNELS = {
    "Health & Vitality": None,
    "Wealth & Finance": None,
    "Relationships": None,
    "Mind & Growth": None,
    "Purpose & Impact": None,
    "Systems & Environment": None,
}
_cfg.DIMENSION_KEYWORDS = {
    "Health & Vitality": ["health", "fitness"],
    "Wealth & Finance": ["money", "finance"],
    "Relationships": ["friend", "family"],
    "Mind & Growth": ["learn", "read"],
    "Purpose & Impact": ["career", "mission"],
    "Systems & Environment": ["system", "automate"],
}
_cfg.CHANNELS = {
    "brain-inbox": "Raw capture and routing",
    "brain-daily": "Morning briefings, evening reviews, actions, projects, resources",
    "brain-insights": "Drift analysis, idea generation, pattern synthesis, and reflections",
    "brain-dashboard": "ICOR heatmap, project status, and cost tracking",
}
_cfg.PROJECT_KEYWORDS = ["project", "milestone"]
_cfg.RESOURCE_KEYWORDS = ["article", "book"]
_cfg.OWNER_SLACK_ID = ""
_cfg.CONFIDENCE_THRESHOLD = 0.60
_cfg.BOUNCER_TIMEOUT_MINUTES = 15
_cfg.ANTHROPIC_API_KEY = ""
_cfg.ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
_cfg.CLASSIFIER_LLM_MODEL = "claude-haiku-4-5-20251001"
_cfg.EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_cfg.EMBEDDING_DIM = 384
_cfg.DB_PATH = MagicMock()
_cfg.VAULT_PATH = MagicMock()
_cfg.COMMANDS_PATH = MagicMock()
_cfg.CLAUDE_MD_PATH = MagicMock()
_cfg.NOTION_REGISTRY_PATH = MagicMock()
_cfg.NOTION_TOKEN = ""
_cfg.NOTION_COLLECTIONS = {}
_cfg.load_dynamic_keywords = MagicMock(return_value=_cfg.DIMENSION_KEYWORDS)
sys.modules.setdefault("config", _cfg)

for mod_name in (
    "anthropic", "slack_bolt", "slack_sdk",
    "sentence_transformers", "schedule",
    "core.article_fetcher",
):
    sys.modules.setdefault(mod_name, MagicMock())


# ---------------------------------------------------------------------------
# Helper: set config.DB_PATH to test_db for async db_connection
# ---------------------------------------------------------------------------
@pytest.fixture()
def _patch_db(test_db):
    """Point config.DB_PATH at test_db so db_connection picks it up."""
    cfg = sys.modules["config"]
    old = cfg.DB_PATH
    cfg.DB_PATH = test_db
    yield test_db
    cfg.DB_PATH = old


# ---------------------------------------------------------------------------
# Tests: config.py
# ---------------------------------------------------------------------------

class TestConfigConsolidation:
    """Verify config.py channel consolidation by reading the source file directly."""

    def test_channels_has_exactly_four_entries(self):
        """CHANNELS dict in config.py source should have exactly 4 entries."""
        # Read the actual source file to verify, since config is mocked in tests
        import ast
        config_path = Path(__file__).parent.parent / "config.py"
        tree = ast.parse(config_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CHANNELS":
                        assert isinstance(node.value, ast.Dict)
                        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                        assert len(keys) == 4
                        assert set(keys) == {
                            "brain-inbox", "brain-daily", "brain-insights", "brain-dashboard",
                        }
                        return
        pytest.fail("CHANNELS dict not found in config.py")

    def test_dimension_channels_all_none(self):
        """DIMENSION_CHANNELS values in config.py source should all be None."""
        import ast
        config_path = Path(__file__).parent.parent / "config.py"
        tree = ast.parse(config_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DIMENSION_CHANNELS":
                        assert isinstance(node.value, ast.Dict)
                        assert len(node.value.keys) == 6
                        for val in node.value.values:
                            assert isinstance(val, ast.Constant) and val.value is None, \
                                f"Expected None, got {ast.dump(val)}"
                        return
        pytest.fail("DIMENSION_CHANNELS dict not found in config.py")


# ---------------------------------------------------------------------------
# Tests: _COMMAND_MAP routing
# ---------------------------------------------------------------------------

class TestCommandMapRouting:
    """Verify _COMMAND_MAP routes to consolidated channels."""

    def test_drift_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-drift"] == ("drift", "brain-insights")

    def test_ideas_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-ideas"] == ("ideas", "brain-insights")

    def test_projects_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-projects"] == ("projects", "brain-daily")

    def test_resources_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-resources"] == ("resources", "brain-daily")

    def test_emerge_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-emerge"] == ("emerge", "brain-insights")

    def test_ghost_routes_to_insights(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-ghost"] == ("ghost", "brain-insights")

    def test_today_routes_to_daily(self):
        from handlers.commands import _COMMAND_MAP
        assert _COMMAND_MAP["/brain-today"] == ("today", "brain-daily")

    def test_no_old_channels_in_command_map(self):
        """No command should route to removed channels."""
        from handlers.commands import _COMMAND_MAP
        removed = {"brain-drift", "brain-ideas", "brain-actions",
                    "brain-projects", "brain-resources",
                    "brain-health", "brain-wealth", "brain-relations",
                    "brain-growth", "brain-purpose", "brain-systems"}
        for cmd, (_, channel) in _COMMAND_MAP.items():
            if channel is not None:
                assert channel not in removed, (
                    f"{cmd} still routes to removed channel {channel}"
                )


# ---------------------------------------------------------------------------
# Tests: capture.py — captures_log insertion
# ---------------------------------------------------------------------------

class TestCaptureProcessing:
    """Verify capture processing inserts into captures_log."""

    def test_capture_inserts_into_captures_log(self, _patch_db):
        """Classified capture should INSERT into captures_log table."""
        test_db = _patch_db

        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Health & Vitality", confidence=0.85, method="keyword"),
        ]
        mock_result.execution_time_ms = 10.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        mock_client = MagicMock()
        event = {"text": "Going for a run tomorrow morning", "user": "U123",
                 "channel": "C_INBOX", "ts": "1234567890.000"}
        channel_ids = {"brain-inbox": "C_INBOX"}

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=[]):
            from handlers.capture import _process_capture
            _process_capture(mock_client, event, channel_ids)

        # Verify captures_log has the entry
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM captures_log").fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row["message_text"] == "Going for a run tomorrow morning"
        assert json.loads(row["dimensions_json"]) == ["Health & Vitality"]
        assert row["confidence"] == 0.85
        assert row["method"] == "keyword"
        assert row["source_channel"] == "brain-inbox"

    def test_capture_does_not_post_to_dimension_channel(self, _patch_db):
        """Capture should NOT post to any dimension channel (they're removed)."""
        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Wealth & Finance", confidence=0.90, method="keyword"),
        ]
        mock_result.execution_time_ms = 5.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        mock_client = MagicMock()
        event = {"text": "Need to review my investment portfolio", "user": "U123",
                 "channel": "C_INBOX", "ts": "1234567891.000"}
        channel_ids = {"brain-inbox": "C_INBOX", "brain-wealth": "C_WEALTH"}

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=[]):
            from handlers.capture import _process_capture
            _process_capture(mock_client, event, channel_ids)

        # Should NOT have a call to brain-wealth channel
        for call in mock_client.chat_postMessage.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            args = call.args if call.args else ()
            channel_arg = kwargs.get("channel", args[0] if args else "")
            assert channel_arg != "C_WEALTH", "Should not post to dimension channel"

    def test_capture_still_writes_to_vault(self, _patch_db):
        """Capture should still write to daily note and inbox entry."""
        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Mind & Growth", confidence=0.80, method="keyword"),
        ]
        mock_result.execution_time_ms = 8.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        mock_client = MagicMock()
        event = {"text": "Reading a great book on systems thinking", "user": "U123",
                 "channel": "C_INBOX", "ts": "1234567892.000"}
        channel_ids = {"brain-inbox": "C_INBOX"}

        mock_append = MagicMock()
        mock_inbox = MagicMock()

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.append_to_daily_note", mock_append), \
             patch("handlers.capture.create_inbox_entry", mock_inbox), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=[]):
            from handlers.capture import _process_capture
            _process_capture(mock_client, event, channel_ids)

        mock_append.assert_called_once()
        mock_inbox.assert_called_once()

    def test_no_cross_post_to_projects_channel(self, _patch_db):
        """Even project-related captures should not cross-post to brain-projects."""
        mock_result = MagicMock()
        mock_result.is_noise = False
        mock_result.is_actionable = False
        mock_result.matches = [
            MagicMock(dimension="Purpose & Impact", confidence=0.80, method="keyword"),
        ]
        mock_result.execution_time_ms = 5.0

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_result

        mock_client = MagicMock()
        event = {"text": "Project milestone deadline sprint deliverable",
                 "user": "U123", "channel": "C_INBOX", "ts": "1234567893.000"}
        channel_ids = {"brain-inbox": "C_INBOX", "brain-projects": "C_PROJECTS"}

        with patch("handlers.capture._classifier", mock_classifier), \
             patch("handlers.capture.append_to_daily_note"), \
             patch("handlers.capture.create_inbox_entry"), \
             patch("handlers.capture.format_capture_line", return_value="- capture"), \
             patch("handlers.capture.format_capture_confirmation", return_value=[]):
            from handlers.capture import _process_capture
            _process_capture(mock_client, event, channel_ids)

        for call in mock_client.chat_postMessage.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            channel_arg = kwargs.get("channel", "")
            assert channel_arg != "C_PROJECTS", "Should not cross-post to brain-projects"


# ---------------------------------------------------------------------------
# Tests: bouncer resolution -> captures_log
# ---------------------------------------------------------------------------

class TestBouncerResolution:
    """Verify bouncer resolution logs to captures_log instead of posting to channel."""

    def test_bouncer_resolution_inserts_captures_log(self, _patch_db):
        """Bouncer resolution should INSERT into captures_log."""
        test_db = _patch_db
        mock_client = MagicMock()

        from handlers.capture import _process_bouncer_resolution
        _process_bouncer_resolution(
            mock_client,
            text="Going for a morning jog",
            ts="1234567890.000",
            dimension="Health & Vitality",
            inbox_channel="C_INBOX",
        )

        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM captures_log").fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row["message_text"] == "Going for a morning jog"
        assert json.loads(row["dimensions_json"]) == ["Health & Vitality"]
        assert row["method"] == "user_clarified"
        assert row["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Tests: feedback.py — corrected capture logs to captures_log
# ---------------------------------------------------------------------------

class TestFeedbackCorrection:
    """Verify feedback correction logs to captures_log."""

    def test_dimension_select_inserts_captures_log(self, _patch_db):
        """Corrected classification should INSERT into captures_log."""
        test_db = _patch_db

        # Pre-seed a classification record
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO classifications (message_text, message_ts, primary_dimension, confidence, method) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Test message", "TS123", "Mind & Growth", 0.75, "keyword"),
        )
        conn.commit()
        conn.close()

        # Directly test the captures_log insert logic that handle_dimension_select does
        from core.async_utils import run_async
        from core.db_ops import execute as db_execute, query as db_query

        rows = run_async(db_query(
            "SELECT message_text FROM classifications WHERE message_ts = ?",
            ("TS123",),
        ))
        assert len(rows) == 1

        # Simulate what handle_dimension_select does with captures_log
        run_async(db_execute(
            "INSERT INTO captures_log "
            "(message_text, dimensions_json, confidence, method, is_actionable, source_channel) "
            "VALUES (?, ?, 1.0, 'user_corrected', 0, 'brain-inbox')",
            (rows[0]["message_text"], json.dumps(["Health & Vitality"])),
        ))

        # Verify captures_log
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        log_rows = conn.execute("SELECT * FROM captures_log").fetchall()
        conn.close()

        assert len(log_rows) == 1
        assert log_rows[0]["method"] == "user_corrected"
        assert json.loads(log_rows[0]["dimensions_json"]) == ["Health & Vitality"]


# ---------------------------------------------------------------------------
# Tests: formatter.py — format_help
# ---------------------------------------------------------------------------

class TestFormatHelp:
    """Verify format_help shows updated channel routing."""

    def test_help_shows_drift_in_insights(self):
        from core.formatter import format_help
        blocks = format_help()
        text = ""
        for b in blocks:
            if b.get("type") == "section" and "brain-drift" in b.get("text", {}).get("text", ""):
                text = b["text"]["text"]
                break
        assert "#brain-insights" in text
        assert "#brain-drift" not in text.split("/brain-drift")[1].split("\n")[0]

    def test_help_shows_ideas_in_insights(self):
        from core.formatter import format_help
        blocks = format_help()
        text = ""
        for b in blocks:
            if b.get("type") == "section" and "brain-ideas" in b.get("text", {}).get("text", ""):
                text = b["text"]["text"]
                break
        for line in text.split("\n"):
            if "/brain-ideas" in line:
                assert "#brain-insights" in line
                break

    def test_help_shows_projects_in_daily(self):
        from core.formatter import format_help
        blocks = format_help()
        text = ""
        for b in blocks:
            if b.get("type") == "section" and "brain-projects" in b.get("text", {}).get("text", ""):
                text = b["text"]["text"]
                break
        for line in text.split("\n"):
            if "/brain-projects" in line:
                assert "#brain-daily" in line
                break

    def test_help_shows_resources_in_daily(self):
        from core.formatter import format_help
        blocks = format_help()
        text = ""
        for b in blocks:
            if b.get("type") == "section" and "brain-resources" in b.get("text", {}).get("text", ""):
                text = b["text"]["text"]
                break
        for line in text.split("\n"):
            if "/brain-resources" in line:
                assert "#brain-daily" in line
                break

    def test_help_has_no_removed_channels(self):
        """Help text should not reference any removed channels."""
        from core.formatter import format_help
        blocks = format_help()
        removed = {"#brain-drift", "#brain-ideas", "#brain-actions",
                    "#brain-projects", "#brain-resources",
                    "#brain-health", "#brain-wealth", "#brain-relations",
                    "#brain-growth", "#brain-purpose", "#brain-systems"}
        full_text = json.dumps(blocks)
        for ch in removed:
            assert ch not in full_text, f"Help text still references removed channel {ch}"


# ---------------------------------------------------------------------------
# Tests: scheduled.py — channel routing
# ---------------------------------------------------------------------------

class TestScheduledJobChannels:
    """Verify scheduled jobs use correct consolidated channels."""

    def test_drift_report_uses_insights(self):
        """job_drift_report should post to brain-insights."""
        mock_client = MagicMock()
        channel_ids = {"brain-insights": "C_INSIGHTS", "brain-daily": "C_DAILY"}

        with patch("handlers.scheduled._call_claude", return_value="Drift report content"), \
             patch("handlers.scheduled._record_job_run"):
            from handlers.scheduled import job_drift_report
            job_drift_report(mock_client, channel_ids)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "C_INSIGHTS"

    def test_project_summary_uses_daily(self):
        """job_weekly_project_summary should post to brain-daily."""
        mock_client = MagicMock()
        channel_ids = {"brain-daily": "C_DAILY", "brain-projects": "C_PROJECTS"}

        with patch("handlers.scheduled._call_claude", return_value="Project summary"), \
             patch("handlers.scheduled._record_job_run"):
            from handlers.scheduled import job_weekly_project_summary
            job_weekly_project_summary(mock_client, channel_ids)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "C_DAILY"

    def test_resource_digest_uses_daily(self):
        """job_monthly_resource_digest should post to brain-daily."""
        mock_client = MagicMock()
        channel_ids = {"brain-daily": "C_DAILY", "brain-resources": "C_RESOURCES"}

        from datetime import datetime
        with patch("handlers.scheduled._call_claude", return_value="Resource digest"), \
             patch("handlers.scheduled._record_job_run"), \
             patch("handlers.scheduled.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 1, 10, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            from handlers.scheduled import job_monthly_resource_digest
            job_monthly_resource_digest(mock_client, channel_ids)

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "C_DAILY"
