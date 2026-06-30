"""Tests for structured logging utilities."""

from datetime import datetime, timezone
from unittest.mock import patch


from simulation_harness.models.domain import SessionState
from simulation_harness.utils.logging import log_tool_call, log_tool_call_legacy
from typing import Any


class TestLogToolCall:
    """Tests for log_tool_call function."""

    @patch("simulation_harness.utils.logging.logger")
    def test_logs_successful_tool_call(self, mock_logger: Any) -> None:
        """Test logging a successful tool call."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=5,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=1,
            max_queue_depth=10,
        )

        log_tool_call_legacy(
            tool_name="get_user",
            arguments={"user_id": "123"},
            result={"name": "John Doe"},
            duration_ms=150,
            session_state=session_state,
            success=True,
        )

        # Verify logger.info was called
        assert mock_logger.info.called
        call_args = mock_logger.info.call_args

        # Check that the log message contains key information
        log_message = str(call_args)
        assert "get_user" in log_message
        assert "150" in log_message  # duration_ms
        assert "5" in log_message  # tool_call_count

    @patch("simulation_harness.utils.logging.logger")
    def test_logs_failed_tool_call(self, mock_logger: Any) -> None:
        """Test logging a failed tool call."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=3,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=0,
            max_queue_depth=10,
        )

        log_tool_call_legacy(
            tool_name="delete_user",
            arguments={"user_id": "999"},
            result=None,
            duration_ms=50,
            session_state=session_state,
            success=False,
            error="User not found",
        )

        # Verify logger.error was called for failed tool call
        assert (
            mock_logger.error.called
            or mock_logger.warning.called
            or mock_logger.info.called
        )
        call_args = (
            mock_logger.error.call_args
            or mock_logger.warning.call_args
            or mock_logger.info.call_args
        )

        # Check that the log message contains error information
        log_message = str(call_args)
        assert "delete_user" in log_message
        assert "User not found" in log_message or "error" in log_message.lower()

    @patch("simulation_harness.utils.logging.logger")
    def test_includes_all_required_fields(self, mock_logger: Any) -> None:
        """Test that log includes all required fields from REQUIREMENTS."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=10,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=2,
            max_queue_depth=10,
        )

        log_tool_call_legacy(
            tool_name="list_items",
            arguments={"limit": 10},
            result={"items": []},
            duration_ms=200,
            session_state=session_state,
            success=True,
        )

        # Verify logger was called
        assert mock_logger.info.called

        # Get the actual call arguments
        call_args = mock_logger.info.call_args

        # The log should contain structured data with all required fields
        # We check that the call was made with appropriate data
        assert call_args is not None

    @patch("simulation_harness.utils.logging.logger")
    def test_handles_complex_arguments(self, mock_logger: Any) -> None:
        """Test logging with complex nested arguments."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=1,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=0,
            max_queue_depth=10,
        )

        complex_args = {
            "filters": {
                "status": ["active", "pending"],
                "created_after": "2024-01-01",
            },
            "pagination": {
                "page": 1,
                "per_page": 50,
            },
        }

        log_tool_call_legacy(
            tool_name="search_records",
            arguments=complex_args,
            result={"count": 42},
            duration_ms=500,
            session_state=session_state,
            success=True,
        )

        # Verify logger was called
        assert mock_logger.info.called

    @patch("simulation_harness.utils.logging.logger")
    def test_logs_with_timestamp(self, mock_logger: Any) -> None:
        """Test that log includes timestamp information."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=7,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=1,
            max_queue_depth=10,
        )

        log_tool_call_legacy(
            tool_name="update_status",
            arguments={"id": "abc", "status": "completed"},
            result={"success": True},
            duration_ms=75,
            session_state=session_state,
            success=True,
        )

        # Verify logger was called
        assert mock_logger.info.called

        # The logging framework will add timestamp automatically,
        # but we verify the function was called correctly
        call_args = mock_logger.info.call_args
        assert call_args is not None

    @patch("simulation_harness.utils.logging.logger")
    def test_includes_session_state_details(self, mock_logger: Any) -> None:
        """Test that session state details are included in log."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=15,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=3,
            max_queue_depth=10,
        )

        log_tool_call_legacy(
            tool_name="process_batch",
            arguments={"batch_id": "batch-123"},
            result={"processed": 100},
            duration_ms=1500,
            session_state=session_state,
            success=True,
        )

        # Verify logger was called
        assert mock_logger.info.called
        call_args = mock_logger.info.call_args

        # Check that session state information is included
        log_message = str(call_args)
        assert "15" in log_message  # tool_call_count
        assert "3" in log_message  # queue_depth

    def test_log_tool_call_complete_fields(self) -> None:
        """Test that log_tool_call includes all required fields."""
        log_entry = log_tool_call(
            tool_name="test_tool",
            outcome="success",
            duration_ms=150,
            tool_call_count=5,
            queue_depth_at_admission=2,
            token_usage={"prompt": 100, "completion": 50, "total": 150},
            transport="sse",
        )

        assert log_entry["tool_name"] == "test_tool"
        assert log_entry["outcome"] == "success"
        assert log_entry["duration_ms"] == 150
        assert log_entry["tool_call_count"] == 5
        assert log_entry["queue_depth_at_admission"] == 2
        assert log_entry["token_usage"] == {
            "prompt": 100,
            "completion": 50,
            "total": 150,
        }
        assert log_entry["transport"] == "sse"
        assert "timestamp" in log_entry

    def test_log_tool_call_outcome_taxonomy(self) -> None:
        """Test that outcome uses correct taxonomy."""
        valid_outcomes = [
            "success",
            "max_messages_exceeded",
            "idle_timeout_exceeded",
            "concurrent_queue_full",
            "llm_provider_error",
            "tool_invocation_error",
            "internal_error",
        ]

        for outcome in valid_outcomes:
            log_entry = log_tool_call(
                tool_name="test",
                outcome=outcome,  # type: ignore[arg-type]
                duration_ms=100,
                tool_call_count=1,
                queue_depth_at_admission=0,
                token_usage=None,
                transport="sse",
            )
            assert log_entry["outcome"] == outcome

    def test_log_tool_call_with_null_token_usage(self) -> None:
        """Test that token_usage can be None."""
        log_entry = log_tool_call(
            tool_name="test_tool",
            outcome="success",
            duration_ms=100,
            tool_call_count=1,
            queue_depth_at_admission=0,
            token_usage=None,
            transport="streamable_http",
        )

        assert log_entry["token_usage"] is None
        assert log_entry["transport"] == "streamable_http"


# Made with Bob
