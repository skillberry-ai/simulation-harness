"""Tests for not-ready 503 + Retry-After behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def pending_host():
    """A SimulationHost mock that always returns a pending record."""
    from simulation_harness.core.simulation_record import SimulationRecord

    host = MagicMock()
    record = SimulationRecord.declare(name="test-api")
    host.get_record = AsyncMock(return_value=record)
    host.get_simulation = AsyncMock(return_value=None)
    return host


@pytest.fixture
def no_record_host():
    """A SimulationHost mock that has no record."""
    host = MagicMock()
    host.get_record = AsyncMock(return_value=None)
    host.get_simulation = AsyncMock(return_value=None)
    return host


@pytest.fixture
def app_with_pending(pending_host):
    """App configured with a pending simulation."""
    from simulation_harness.main import app
    from simulation_harness.api.dependencies import get_simulation_host

    app.dependency_overrides[get_simulation_host] = lambda: pending_host
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def app_with_no_record(no_record_host):
    """App configured with no simulation."""
    from simulation_harness.main import app
    from simulation_harness.api.dependencies import get_simulation_host

    app.dependency_overrides[get_simulation_host] = lambda: no_record_host
    yield app
    app.dependency_overrides.clear()


def test_mcp_messages_503_when_simulation_pending(app_with_pending):
    """When record exists but is pending, MCP endpoints return 503 with Retry-After."""
    client = TestClient(app_with_pending, raise_server_exceptions=False)
    resp = client.post("/mcp/messages", content=b"{}")
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "2"


def test_mcp_messages_404_when_no_record(app_with_no_record):
    """When no simulation has been declared, MCP endpoints return 404."""
    client = TestClient(app_with_no_record, raise_server_exceptions=False)
    resp = client.post("/mcp/messages", content=b"{}")
    assert resp.status_code == 404
