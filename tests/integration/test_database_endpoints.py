"""Integration coverage for /simulation/database and /simulation/schema."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient
from collections.abc import Iterator
from typing import Any


@pytest.fixture(scope="module", autouse=True)
def _harness_env() -> Iterator[None]:
    config = {
        "llm": {
            "provider": "openai",
            "skill_generation_model": "gpt-4",
            "simulation_model": "gpt-4",
            "temperature": 0,
        },
        "skills": {"folder": "./skills"},
        "sessions": {
            "max_messages": 100,
            "idle_timeout_seconds": 3600,
            "max_concurrent_queue_depth": 8,
        },
        "mcp": {"transport": "sse"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        path = f.name

    prior_key = os.environ.get("LLM_API_KEY")
    prior_cfg = os.environ.get("HARNESS_CONFIG_PATH")
    os.environ["LLM_API_KEY"] = "test-key"
    os.environ["HARNESS_CONFIG_PATH"] = path
    try:
        yield
    finally:
        os.unlink(path)
        if prior_key is not None:
            os.environ["LLM_API_KEY"] = prior_key
        else:
            os.environ.pop("LLM_API_KEY", None)
        if prior_cfg is not None:
            os.environ["HARNESS_CONFIG_PATH"] = prior_cfg
        else:
            os.environ.pop("HARNESS_CONFIG_PATH", None)


@pytest.fixture
def skill_bundle(tmp_path: Path) -> tuple[Path, str]:
    """Write a minimal complete skill bundle on disk; return (skills_folder, name)."""
    name = "demo-api"
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text("# demo")
    (d / "api.json").write_text("{}")
    (d / "schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}
                },
                "$defs": {
                    "Item": {
                        "type": "object",
                        "required": ["id", "name"],
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                        },
                        "x-primary-key": "id",
                    }
                },
            }
        )
    )
    (d / "db.json").write_text(json.dumps({"items": [{"id": "1", "name": "alpha"}]}))
    return tmp_path, name


def _make_app_with(skills_folder: Path, simulation_name: str) -> Any:
    """Use the real FastAPI app with dependency overrides for isolated testing."""
    import importlib

    import simulation_harness.main as m

    importlib.reload(m)

    from simulation_harness.api.dependencies import (
        get_simulation_host,
        get_skill_registry,
    )
    from simulation_harness.core.simulation_host import SimulationHost
    from simulation_harness.core.simulation_record import (
        SimulationRecord,
        SimulationStatus,
    )
    from simulation_harness.core.skill_registry import SkillRegistry
    from simulation_harness.models.domain import SessionState

    skill_registry = SkillRegistry(skills_folder=skills_folder, generator=None)  # type: ignore[arg-type]

    host = SimulationHost()
    instance = MagicMock()
    instance.get_session_state.return_value = SessionState(
        tool_call_count=0,
        max_messages=100,
        idle_timeout_seconds=3600,
        last_activity=None,
        queue_depth=0,
        max_queue_depth=8,
    )
    instance.reset_session = AsyncMock()
    instance.mcp_port = None
    record = SimulationRecord.declare(name=simulation_name)
    record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
    record.mark_ready(instance)
    host._record = record

    m.app.dependency_overrides[get_simulation_host] = lambda: host
    m.app.dependency_overrides[get_skill_registry] = lambda: skill_registry
    return m.app, host, skill_registry, instance


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    yield
    import importlib

    import simulation_harness.main as m

    importlib.reload(m)
    m.app.dependency_overrides.clear()


class TestDatabaseEndpointsIntegration:
    def test_get_schema_returns_disk_contents(
        self, skill_bundle: tuple[Path, str]
    ) -> None:
        skills_folder, name = skill_bundle
        app, *_ = _make_app_with(skills_folder, name)
        with TestClient(app) as client:
            resp = client.get("/api/v1/simulation/schema")
        assert resp.status_code == 200
        assert resp.json()["$defs"]["Item"]["x-primary-key"] == "id"

    def test_get_database_returns_disk_contents(
        self, skill_bundle: tuple[Path, str]
    ) -> None:
        skills_folder, name = skill_bundle
        app, *_ = _make_app_with(skills_folder, name)
        with TestClient(app) as client:
            resp = client.get("/api/v1/simulation/database")
        assert resp.status_code == 200
        assert resp.json() == {"items": [{"id": "1", "name": "alpha"}]}

    def test_put_database_replaces_file_and_resets_instance(
        self, skill_bundle: tuple[Path, str]
    ) -> None:
        skills_folder, name = skill_bundle
        app, _host, _registry, instance = _make_app_with(skills_folder, name)

        new_db = {"items": [{"id": "2", "name": "beta"}]}
        with TestClient(app) as client:
            resp = client.put("/api/v1/simulation/database", json=new_db)

        assert resp.status_code == 200
        assert json.loads((skills_folder / name / "db.json").read_text()) == new_db
        instance.reset_session.assert_awaited_once()

    def test_put_invalid_database_returns_422_and_does_not_reset(
        self, skill_bundle: tuple[Path, str]
    ) -> None:
        skills_folder, name = skill_bundle
        app, _host, _registry, instance = _make_app_with(skills_folder, name)
        original = (skills_folder / name / "db.json").read_text()

        bad_db = {"items": [{"id": "x"}]}  # missing "name"
        with TestClient(app) as client:
            resp = client.put("/api/v1/simulation/database", json=bad_db)

        assert resp.status_code == 422
        assert (skills_folder / name / "db.json").read_text() == original
        instance.reset_session.assert_not_awaited()
