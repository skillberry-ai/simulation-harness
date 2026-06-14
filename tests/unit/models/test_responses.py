"""Tests for API response models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from simulation_harness.models.domain import SessionState
from simulation_harness.models.responses import SimulationResponse


class TestSimulationResponse:
    """Tests for SimulationResponse model."""

    def test_create_with_all_fields(self):
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
            status="running",
            session_state=session_state,
            mcp_url="http://localhost:8000/mcp/test-simulation",
            created_at=now,
        )

        assert response.name == "test-simulation"
        assert response.status == "running"
        assert response.session_state == session_state
        assert response.mcp_url == "http://localhost:8000/mcp/test-simulation"
        assert response.created_at == now

    def test_all_fields_required(self):
        """Test that all fields are required."""
        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse()

        error_str = str(exc_info.value)
        assert "name" in error_str
        assert "status" in error_str
        assert "session_state" in error_str
        assert "mcp_url" in error_str
        assert "created_at" in error_str

    def test_session_state_must_be_valid(self):
        """Test that session_state must be a valid SessionState object."""
        now = datetime.now(timezone.utc)

        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse(
                name="test-simulation",
                status="running",
                session_state={"invalid": "dict"},
                mcp_url="http://localhost:8000/mcp/test-simulation",
                created_at=now,
            )

        assert "session_state" in str(exc_info.value)

    def test_created_at_must_be_datetime(self):
        """Test that created_at must be a datetime object."""
        now = datetime.now(timezone.utc)
        session_state = SessionState(
            tool_call_count=0,
            max_messages=100,
            idle_timeout_seconds=300,
            last_activity=now,
            queue_depth=0,
            max_queue_depth=10,
        )

        with pytest.raises(ValidationError) as exc_info:
            SimulationResponse(
                name="test-simulation",
                status="running",
                session_state=session_state,
                mcp_url="http://localhost:8000/mcp/test-simulation",
                created_at="not a datetime",
            )

        assert "created_at" in str(exc_info.value)

    def test_response_serialization(self):
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
            status="running",
            session_state=session_state,
            mcp_url="http://localhost:8000/mcp/test-simulation",
            created_at=now,
        )

        response_dict = response.model_dump()

        assert response_dict["name"] == "test-simulation"
        assert response_dict["status"] == "running"
        assert response_dict["session_state"]["tool_call_count"] == 3
        assert response_dict["mcp_url"] == "http://localhost:8000/mcp/test-simulation"
        assert isinstance(response_dict["created_at"], datetime)


# Made with Bob
