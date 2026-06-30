"""Tests for domain models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from simulation_harness.models.domain import (
    SessionState,
    SimulationSpec,
    ToolCallResult,
)


class TestSimulationSpec:
    """Tests for SimulationSpec model."""

    def test_create_with_minimal_fields(self) -> None:
        """Test creating SimulationSpec with minimal required fields."""
        spec = SimulationSpec(
            name="test-simulation",
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
        )

        assert spec.name == "test-simulation"
        assert spec.openapi_spec["openapi"] == "3.0.0"
        assert spec.regenerate_skill is False  # default value

    def test_create_with_regenerate_skill(self) -> None:
        """Test creating SimulationSpec with regenerate_skill flag."""
        spec = SimulationSpec(
            name="test-simulation",
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
            regenerate_skill=True,
        )

        assert spec.regenerate_skill is True

    def test_openapi_spec_must_be_dict(self) -> None:
        """Test that openapi_spec must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            SimulationSpec(
                name="test-simulation",
                openapi_spec="not a dict",
            )

        assert "openapi_spec" in str(exc_info.value)

    def test_name_required(self) -> None:
        """Test that name is required."""
        with pytest.raises(ValidationError) as exc_info:
            SimulationSpec(  # type: ignore[call-arg]
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "Test", "version": "1.0.0"},
                },
            )

        assert "name" in str(exc_info.value)


class TestSessionState:
    """Tests for SessionState model."""

    def test_create_with_all_fields(self) -> None:
        """Test creating SessionState with all fields."""
        now = datetime.now(timezone.utc)
        state = SessionState(
            tool_call_count=5,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=2,
            max_queue_depth=10,
        )

        assert state.tool_call_count == 5
        assert state.max_messages == 100
        assert state.idle_timeout_seconds == 300
        assert state.last_activity == now
        assert state.queue_depth == 2
        assert state.max_queue_depth == 10

    def test_default_values(self) -> None:
        """Test default values for SessionState."""
        state = SessionState(
            tool_call_count=0,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=datetime.now(timezone.utc),
            queue_depth=0,
            max_queue_depth=10,
        )

        assert state.tool_call_count == 0
        assert state.queue_depth == 0

    def test_all_fields_required(self) -> None:
        """Test that all fields are required."""
        with pytest.raises(ValidationError) as exc_info:
            SessionState()  # type: ignore[call-arg]

        error_str = str(exc_info.value)
        assert "tool_call_count" in error_str
        assert "max_messages" in error_str
        assert "idle_timeout_seconds" in error_str
        assert "last_activity" in error_str
        assert "queue_depth" in error_str
        assert "max_queue_depth" in error_str

    def test_negative_counts_invalid(self) -> None:
        """Test that negative counts are invalid."""
        now = datetime.now(timezone.utc)

        with pytest.raises(ValidationError):
            SessionState(
                tool_call_count=-1,
                max_messages=100,
                idle_timeout_seconds=300,
                last_activity=now,
                queue_depth=0,
                max_queue_depth=10,
            )

    def test_session_state_seconds_since_last_call(self) -> None:
        """Test that SessionState includes seconds_since_last_call."""
        from datetime import timedelta

        last_activity = datetime.now(timezone.utc) - timedelta(seconds=45)

        state = SessionState(
            tool_call_count=5,
            max_messages=100,
            idle_timeout_seconds=3600,
            last_activity=last_activity,
            queue_depth=2,
            max_queue_depth=8,
        )

        # Should compute seconds since last call
        assert hasattr(state, "seconds_since_last_call")
        assert state.seconds_since_last_call is not None
        assert 44 <= state.seconds_since_last_call <= 46  # Allow 1s tolerance

    def test_session_state_seconds_since_last_call_none(self) -> None:
        """Test seconds_since_last_call when last_activity is None."""
        state = SessionState(
            tool_call_count=0,
            max_messages=100,
            idle_timeout_seconds=3600,
            last_activity=None,
            queue_depth=0,
            max_queue_depth=8,
        )

        assert state.seconds_since_last_call is None


class TestToolCallResult:
    """Tests for ToolCallResult model."""

    def test_successful_result(self) -> None:
        """Test creating a successful ToolCallResult."""
        result = ToolCallResult(
            success=True,
            content="Operation completed successfully",
        )

        assert result.success is True
        assert result.content == "Operation completed successfully"
        assert result.error is None

    def test_failed_result_with_error(self) -> None:
        """Test creating a failed ToolCallResult with error."""
        result = ToolCallResult(
            success=False,
            content="",
            error="Something went wrong",
        )

        assert result.success is False
        assert result.content == ""
        assert result.error == "Something went wrong"

    def test_success_required(self) -> None:
        """Test that success field is required."""
        with pytest.raises(ValidationError) as exc_info:
            ToolCallResult(content="test")  # type: ignore[call-arg]

        assert "success" in str(exc_info.value)

    def test_content_required(self) -> None:
        """Test that content field is required."""
        with pytest.raises(ValidationError) as exc_info:
            ToolCallResult(success=True)  # type: ignore[call-arg]

        assert "content" in str(exc_info.value)

    def test_error_optional(self) -> None:
        """Test that error field is optional."""
        result = ToolCallResult(
            success=True,
            content="test",
        )

        assert result.error is None


# Made with Bob
