"""Integration tests for test client functionality."""

import json
from pathlib import Path

import pytest
import yaml

from src.ui_components import load_spec_from_file


class TestExampleFilesIntegration:
    """Integration tests for loading example files."""
    
    def test_load_sample_yaml_file(self):
        """Test loading the actual sample YAML file."""
        file_path = Path("examples/sample_openapi.yaml")
        
        # Skip if file doesn't exist (CI environment)
        if not file_path.exists():
            pytest.skip("Example file not found")
        
        spec = load_spec_from_file(str(file_path))
        
        assert spec is not None
        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Sample Calculator API"
        assert "/add" in spec["paths"]
        assert "/multiply" in spec["paths"]
    
    def test_load_sample_json_file(self):
        """Test loading the actual sample JSON file."""
        file_path = Path("examples/sample_openapi.json")
        
        # Skip if file doesn't exist (CI environment)
        if not file_path.exists():
            pytest.skip("Example file not found")
        
        spec = load_spec_from_file(str(file_path))
        
        assert spec is not None
        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Sample Calculator API"
        assert "/add" in spec["paths"]
        assert "/multiply" in spec["paths"]
    
    def test_yaml_and_json_produce_same_spec(self):
        """Test that YAML and JSON versions produce equivalent specs."""
        yaml_path = Path("examples/sample_openapi.yaml")
        json_path = Path("examples/sample_openapi.json")
        
        # Skip if files don't exist
        if not yaml_path.exists() or not json_path.exists():
            pytest.skip("Example files not found")
        
        yaml_spec = load_spec_from_file(str(yaml_path))
        json_spec = load_spec_from_file(str(json_path))
        
        assert yaml_spec is not None
        assert json_spec is not None
        
        # Compare key fields
        assert yaml_spec["openapi"] == json_spec["openapi"]
        assert yaml_spec["info"] == json_spec["info"]
        assert set(yaml_spec["paths"].keys()) == set(json_spec["paths"].keys())


import httpx

from src.api_client import HarnessAPIClient


@pytest.mark.asyncio
async def test_get_simulation_state_returns_state_payload():
    """Test the API client fetches simulation state from the state endpoint."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "cart": {"items": [{"sku": "abc", "quantity": 2}]},
                "user": {"id": "user-123"},
            },
        )
        if request.method == "GET" and request.url.path == "/api/v1/simulation/state"
        else httpx.Response(404, json={"detail": "not found"})
    )

    client = HarnessAPIClient("http://testserver")
    client.client = httpx.AsyncClient(transport=transport, timeout=120.0)

    try:
        response = await client.get_simulation_state()
    finally:
        await client.close()

    assert response.success is True
    assert response.status_code == 200
    assert response.data == {
        "cart": {"items": [{"sku": "abc", "quantity": 2}]},
        "user": {"id": "user-123"},
    }
    assert response.error is None


@pytest.mark.asyncio
async def test_get_simulation_state_forwards_thread_id_query_param():
    """Test the API client forwards thread_id to the simulation state endpoint."""
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["path"] = request.url.path
        captured_request["thread_id"] = request.url.params.get("thread_id")
        return httpx.Response(200, json={"orders": []})

    transport = httpx.MockTransport(handler)

    client = HarnessAPIClient("http://testserver")
    client.client = httpx.AsyncClient(transport=transport, timeout=120.0)

    try:
        response = await client.get_simulation_state(thread_id="thread-42")
    finally:
        await client.close()

    assert response.success is True
    assert response.status_code == 200
    assert captured_request == {
        "path": "/api/v1/simulation/state",
        "thread_id": "thread-42",
    }


@pytest.mark.asyncio
async def test_get_simulation_state_returns_error_for_missing_simulation():
    """Test the API client surfaces a 404 when no simulation exists."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            404,
            json={"detail": "No simulation found"},
        )
    )

    client = HarnessAPIClient("http://testserver")
    client.client = httpx.AsyncClient(transport=transport, timeout=120.0)

    try:
        response = await client.get_simulation_state()
    finally:
        await client.close()

    assert response.success is False
    assert response.status_code == 404
    assert response.data is None
    assert "No simulation found" in response.error


def test_app_includes_simulation_state_ui():
    """Test the Streamlit app exposes a simulation state section in the API tab."""
    app_source = Path("app.py").read_text()

    assert "Get Simulation State" in app_source
    assert "/api/v1/simulation/state" in app_source
# Made with Bob
