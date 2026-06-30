"""Tests for API response models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from simulation_harness.models.domain import SessionState
from simulation_harness.models.responses import ProgressPayload, SimulationResponse
from typing import Any


def _make_progress(now: Any) -> ProgressPayload:
    return ProgressPayload(phase=None, started_at=now, updated_at=now)


class TestSimulationResponse:
    """Tests for SimulationResponse model."""

    def test_create_with_all_fields(self) -> None:
        """Test creating response with all fields."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=5,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=2,
            max_queue_depth=10,
        )

        response = SimulationResponse(
            name="test-simulation",
            status="ready",
            session_state=session_state,
            mcp_url="http://localhost:8000/mcp/test-simulation",
            created_at=now,
            progress=_make_progress(now),
        )

        assert response.name == "test-simulation"
        assert response.status == "ready"
        assert response.session_state == session_state
        assert response.mcp_url == "http://localhost:8000/mcp/test-simulation"
        assert response.created_at == now

    def test_required_fields(self) -> None:
        """Test that name, status, created_at, and progress are required."""
        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse()  # type: ignore[call-arg]

        error_str = str(exc_info.value)
        assert "name" in error_str
        assert "status" in error_str
        assert "created_at" in error_str
        assert "progress" in error_str

    def test_optional_fields_default_to_none(self) -> None:
        """Test that session_state, mcp_url, and error default to None."""
        now = datetime.now(timezone.utc)
        response = SimulationResponse(
            name="test-simulation",
            status="pending",
            created_at=now,
            progress=_make_progress(now),
        )
        assert response.session_state is None
        assert response.mcp_url is None
        assert response.error is None

    def test_session_state_must_be_valid(self) -> None:
        """Test that session_state must be a valid SessionState object."""
        now = datetime.now(timezone.utc)

        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse(
                name="test-simulation",
                status="ready",
                session_state={"invalid": "dict"},
                mcp_url="http://localhost:8000/mcp/test-simulation",
                created_at=now,
                progress=_make_progress(now),
            )

        assert "session_state" in str(exc_info.value)

    def test_created_at_must_be_datetime(self) -> None:
        """Test that created_at must be a datetime object."""
        now = datetime.now(timezone.utc)

        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse(
                name="test-simulation",
                status="running",
                created_at="not a datetime",
                progress=_make_progress(now),
            )

        assert "created_at" in str(exc_info.value)

    def test_response_serialization(self) -> None:
        """Test that response can be serialized to dict."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=3,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=1,
            max_queue_depth=10,
        )

        response = SimulationResponse(
            name="test-simulation",
            status="ready",
            session_state=session_state,
            mcp_url="http://localhost:8000/mcp/test-simulation",
            created_at=now,
            progress=_make_progress(now),
        )

        response_dict = response.model_dump()

        assert response_dict["name"] == "test-simulation"
        assert response_dict["status"] == "ready"
        assert response_dict["session_state"]["tool_call_count"] == 3
        assert response_dict["mcp_url"] == "http://localhost:8000/mcp/test-simulation"
        assert isinstance(response_dict["created_at"], datetime)


# Made with Bob
