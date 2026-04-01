"""Tests for cross-session trend queries and alert optimizations."""
import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("config", MagicMock())



class TestTrendQueries:
    def test_today_has_mood_energy_7d(self):
        from core.context_loader import _COMMAND_QUERIES
        assert "today" in _COMMAND_QUERIES
        assert "mood_energy_7d" in _COMMAND_QUERIES["today"]

    def test_today_has_engagement_trend_7d(self):
        from core.context_loader import _COMMAND_QUERIES
        assert "engagement_trend_7d" in _COMMAND_QUERIES["today"]

    def test_schedule_has_mood_energy_30d(self):
        from core.context_loader import _COMMAND_QUERIES
        assert "schedule" in _COMMAND_QUERIES
        assert "mood_energy_30d" in _COMMAND_QUERIES["schedule"]

    def test_schedule_has_engagement_trend_30d(self):
        from core.context_loader import _COMMAND_QUERIES
        assert "engagement_trend_30d" in _COMMAND_QUERIES["schedule"]

    def test_existing_today_queries_preserved(self):
        from core.context_loader import _COMMAND_QUERIES
        # Verify we didn't delete existing queries
        today_keys = set(_COMMAND_QUERIES["today"].keys())
        assert "pending_actions" in today_keys
        assert "neglected" in today_keys
        assert "recent_journal" in today_keys
        assert len(today_keys) >= 5  # 3 original + 2 new

    def test_existing_schedule_queries_preserved(self):
        from core.context_loader import _COMMAND_QUERIES
        schedule_keys = set(_COMMAND_QUERIES["schedule"].keys())
        assert "energy_patterns" in schedule_keys
        assert "pending_actions" in schedule_keys
        assert "dimension_coverage" in schedule_keys
        assert len(schedule_keys) >= 5  # 3 original + 2 new


class TestRunAllChecks:
    def test_returns_dict_with_expected_keys(self):
        from core.alerts import run_all_checks
        with patch("core.alerts.check_stale_actions", return_value=0), \
             patch("core.alerts.check_neglected_dimensions", return_value=0), \
             patch("core.alerts.check_engagement_drop", return_value=0), \
             patch("core.alerts.check_streak_break", return_value=0), \
             patch("core.alerts.check_drift_alerts", return_value=0), \
             patch("core.alerts.check_knowledge_gaps", return_value=0):
            result = run_all_checks("/dev/null")
            assert isinstance(result, dict)
            assert "total_new" in result
            assert "by_type" in result
            assert result["total_new"] == 0

    def test_continues_on_checker_error(self):
        from core.alerts import run_all_checks
        with patch("core.alerts.check_stale_actions", side_effect=Exception("boom")), \
             patch("core.alerts.check_neglected_dimensions", return_value=2), \
             patch("core.alerts.check_engagement_drop", return_value=0), \
             patch("core.alerts.check_streak_break", return_value=0), \
             patch("core.alerts.check_drift_alerts", return_value=0), \
             patch("core.alerts.check_knowledge_gaps", return_value=0):
            result = run_all_checks("/dev/null")
            # stale_actions failed -> 0, neglected_dimension -> 2
            assert result["total_new"] == 2
            assert result["by_type"]["stale_actions"] == 0
            assert result["by_type"]["neglected_dimension"] == 2

    def test_aggregates_counts(self):
        from core.alerts import run_all_checks
        with patch("core.alerts.check_stale_actions", return_value=3), \
             patch("core.alerts.check_neglected_dimensions", return_value=1), \
             patch("core.alerts.check_engagement_drop", return_value=0), \
             patch("core.alerts.check_streak_break", return_value=1), \
             patch("core.alerts.check_drift_alerts", return_value=0), \
             patch("core.alerts.check_knowledge_gaps", return_value=2):
            result = run_all_checks("/dev/null")
            assert result["total_new"] == 7
