"""Tests for core.distiller — conversation distillation pipeline."""
import json
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

cfg = sys.modules["config"]
cfg.CLASSIFIER_LLM_MODEL = "claude-haiku-4-5-20251001"
cfg.VAULT_PATH = Path("/tmp/test-vault")
cfg.CONVERSATIONS_PATH = Path("/tmp/nonexistent-conversations")


@pytest.fixture
def sample_notes():
    return [
        {
            "title": "WAL mode prevents read locks",
            "content": "SQLite WAL mode allows concurrent readers.",
            "category": "explanation",
            "related_topics": ["sqlite", "concurrency"],
        },
        {
            "title": "Batch mode for bulk writes",
            "content": "Enter batch mode to suppress post-write hooks.",
            "category": "pattern",
            "related_topics": ["vault", "performance"],
        },
    ]


@pytest.fixture
def mock_ai_response(sample_notes):
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(sample_notes))]
    return response


class TestDistillSession:
    @pytest.mark.asyncio
    async def test_extracts_notes_from_valid_response(self, tmp_path, mock_ai_response, sample_notes):
        session = tmp_path / "session.jsonl"
        # Write enough assistant content
        lines = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "a" * 300}]}}
        ]
        with open(session, "w") as f:
            for obj in lines:
                f.write(json.dumps(obj) + "\n")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_ai_response)

        with patch("core.distiller.get_ai_client", return_value=mock_client):
            from core.distiller import distill_session
            notes = await distill_session(session, "test-session")

        assert len(notes) == 2
        assert notes[0]["title"] == "WAL mode prevents read locks"

    @pytest.mark.asyncio
    async def test_handles_markdown_code_fence(self, tmp_path):
        session = tmp_path / "session.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "x" * 300}]},
            }) + "\n")

        fenced_json = '```json\n[{"title": "Test", "content": "Body", "category": "pattern", "related_topics": []}]\n```'
        response = MagicMock()
        response.content = [MagicMock(text=fenced_json)]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("core.distiller.get_ai_client", return_value=mock_client):
            from core.distiller import distill_session
            notes = await distill_session(session, "test-session")

        assert len(notes) == 1
        assert notes[0]["title"] == "Test"

    @pytest.mark.asyncio
    async def test_returns_empty_on_short_content(self, tmp_path):
        session = tmp_path / "session.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "short"}]},
            }) + "\n")

        from core.distiller import distill_session
        notes = await distill_session(session, "test-session")
        assert notes == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_ai_client(self, tmp_path):
        session = tmp_path / "session.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "x" * 300}]},
            }) + "\n")

        with patch("core.distiller.get_ai_client", return_value=None):
            from core.distiller import distill_session
            notes = await distill_session(session, "test-session")

        assert notes == []

    @pytest.mark.asyncio
    async def test_handles_invalid_json_response(self, tmp_path):
        session = tmp_path / "session.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "x" * 300}]},
            }) + "\n")

        response = MagicMock()
        response.content = [MagicMock(text="not valid json at all")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("core.distiller.get_ai_client", return_value=mock_client):
            from core.distiller import distill_session
            notes = await distill_session(session, "test-session")

        assert notes == []

    @pytest.mark.asyncio
    async def test_caps_at_five_notes(self, tmp_path, mock_ai_response):
        session = tmp_path / "session.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "x" * 300}]},
            }) + "\n")

        many_notes = [{"title": f"Note {i}", "content": "Body", "category": "pattern", "related_topics": []} for i in range(8)]
        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(many_notes))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("core.distiller.get_ai_client", return_value=mock_client):
            from core.distiller import distill_session
            notes = await distill_session(session, "test-session")

        assert len(notes) == 5


class TestBuildBatches:
    def test_single_item(self):
        from core.distiller import _build_batches
        items = [("s1", "text one")]
        batches = _build_batches(items)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_splits_on_char_limit(self):
        from core.distiller import _build_batches
        items = [
            ("s1", "a" * 5000),
            ("s2", "b" * 5000),
            ("s3", "c" * 5000),
        ]
        batches = _build_batches(items, batch_char_limit=9000)
        assert len(batches) == 3  # Each item is 5000 chars, limit 9000

    def test_groups_small_items(self):
        from core.distiller import _build_batches
        items = [
            ("s1", "a" * 1000),
            ("s2", "b" * 1000),
            ("s3", "c" * 1000),
        ]
        batches = _build_batches(items, batch_char_limit=5000)
        assert len(batches) == 1  # All fit in one batch

    def test_empty_input(self):
        from core.distiller import _build_batches
        assert _build_batches([]) == []

    def test_truncates_long_text(self):
        from core.distiller import _build_batches, _CHARS_PER_CONV
        items = [("s1", "x" * 100_000)]  # Way over _CHARS_PER_CONV
        batches = _build_batches(items)
        assert len(batches) == 1
        assert len(batches[0][0][1]) == _CHARS_PER_CONV


class TestDistillSessions:
    @pytest.mark.asyncio
    async def test_writes_notes_with_provenance(self, tmp_path, sample_notes):
        # Set up a session file that passes should_distill
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        long_text = "a" * 3000
        padding = [{"type": "user", "message": {"content": "x" * 500}} for _ in range(20)]
        lines = padding + [{"type": "assistant", "message": {"content": [{"type": "text", "text": long_text}]}}]
        with open(session, "w") as f:
            for obj in lines:
                f.write(json.dumps(obj) + "\n")

        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(sample_notes))]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        mock_execute = AsyncMock()
        mock_query = AsyncMock(return_value=[])

        with (
            patch("core.distiller.get_ai_client", return_value=mock_client),
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.distiller.snapshot_vault_before_batch"),
            patch("core.distiller.enter_batch_mode"),
            patch("core.distiller.exit_batch_mode"),
            patch("core.distiller.validate_vault_write", return_value=[]),
            patch("core.distiller.create_inbox_entry") as mock_create,
            patch("core.db_ops.query", mock_query),
        ):
            from core.distiller import distill_sessions
            sessions_done, notes_created = await distill_sessions(mock_execute, limit=5)

        assert sessions_done == 1
        assert notes_created == 2
        # Verify provenance
        calls = mock_create.call_args_list
        assert all(c.kwargs.get("source") == "distiller" for c in calls)
        assert all(c.kwargs.get("source_session") == "abc123" for c in calls)

    @pytest.mark.asyncio
    async def test_quality_gate_rejects_note(self, tmp_path, sample_notes):
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 300}]}}) + "\n")

        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(sample_notes))]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        mock_execute = AsyncMock()

        with (
            patch("core.distiller.get_ai_client", return_value=mock_client),
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.distiller.snapshot_vault_before_batch"),
            patch("core.distiller.enter_batch_mode"),
            patch("core.distiller.exit_batch_mode"),
            patch("core.distiller.validate_vault_write", return_value=["broken wikilink"]),
            patch("core.distiller.create_inbox_entry") as mock_create,
            patch("core.db_ops.query", AsyncMock(return_value=[])),
        ):
            from core.distiller import distill_sessions
            sessions_done, notes_created = await distill_sessions(mock_execute, limit=5)

        assert sessions_done == 1
        assert notes_created == 0
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_distilled(self, tmp_path, sample_notes):
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 300}]}}) + "\n")

        mock_execute = AsyncMock()
        already_done = [{"session_path": str(session)}]

        with (
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.db_ops.query", AsyncMock(return_value=already_done)),
        ):
            from core.distiller import distill_sessions
            sessions_done, notes_created = await distill_sessions(mock_execute, limit=5)

        assert sessions_done == 0
        assert notes_created == 0

    @pytest.mark.asyncio
    async def test_batch_mode_wraps_writes(self, tmp_path, sample_notes):
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 300}]}}) + "\n")

        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(sample_notes))]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        mock_execute = AsyncMock()

        with (
            patch("core.distiller.get_ai_client", return_value=mock_client),
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.distiller.snapshot_vault_before_batch") as mock_snap,
            patch("core.distiller.enter_batch_mode") as mock_enter,
            patch("core.distiller.exit_batch_mode") as mock_exit,
            patch("core.distiller.validate_vault_write", return_value=[]),
            patch("core.distiller.create_inbox_entry"),
            patch("core.db_ops.query", AsyncMock(return_value=[])),
        ):
            from core.distiller import distill_sessions
            await distill_sessions(mock_execute, limit=5)

        mock_snap.assert_called_once_with("distill")
        mock_enter.assert_called_once()
        mock_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_to_distill_log(self, tmp_path, sample_notes):
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 300}]}}) + "\n")

        response = MagicMock()
        response.content = [MagicMock(text=json.dumps(sample_notes))]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)
        mock_execute = AsyncMock()

        with (
            patch("core.distiller.get_ai_client", return_value=mock_client),
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.distiller.snapshot_vault_before_batch"),
            patch("core.distiller.enter_batch_mode"),
            patch("core.distiller.exit_batch_mode"),
            patch("core.distiller.validate_vault_write", return_value=[]),
            patch("core.distiller.create_inbox_entry"),
            patch("core.db_ops.query", AsyncMock(return_value=[])),
        ):
            from core.distiller import distill_sessions
            await distill_sessions(mock_execute, limit=5)

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert "INSERT OR IGNORE INTO distill_log" in call_args[0][0]
        assert call_args[0][1][1] == "abc123"  # session_id

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_ai_client(self, tmp_path):
        session_dir = tmp_path / "projects"
        session_dir.mkdir()
        session = session_dir / "abc123.jsonl"
        with open(session, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 300}]}}) + "\n")

        mock_execute = AsyncMock()

        with (
            patch("core.distiller.get_ai_client", return_value=None),
            patch("core.distiller.find_session_files", return_value=[session]),
            patch("core.distiller.should_distill", return_value=True),
            patch("core.db_ops.query", AsyncMock(return_value=[])),
        ):
            from core.distiller import distill_sessions
            sessions_done, notes_created = await distill_sessions(mock_execute, limit=5)

        assert sessions_done == 0
        assert notes_created == 0
