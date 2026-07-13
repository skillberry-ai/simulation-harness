"""End-to-end autostart-from-mounted-volume behavior at boot.

Drives the real FastAPI lifespan via TestClient against a temp skills folder
(the durable ``HARNESS_SKILLS_FOLDER`` location), covering the volume states the
generic-image epic relies on:

- empty volume  → pod boots idle and healthy, ready to accept a spec;
- populated volume (one baked bundle) → autostart to ``ready``, no regeneration;
- ``HARNESS_AUTOSTART_SIMULATION`` set → that named skill starts (wins over
  most-recent);
- unset + multiple bundles → most-recent bundle starts.

Agent construction is lazy (no live LLM), so a fake key reaches ``ready`` the
same way the lifecycle integration tests do.
"""

import importlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient
from collections.abc import Iterator

from tests.integration.conftest import poll_until_ready

# Minimal valid OpenAPI spec baked into api.json — start (generate=False) reads
# it back and builds the tool surface from it, so it needs one real operation.
MINIMAL_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Autostart API", "version": "1.0.0"},
    "paths": {
        "/test": {
            "get": {
                "operationId": "getTest",
                "summary": "Get test data",
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"message": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}


def _bake_skill(folder: Path, name: str, *, mtime: int | None = None) -> None:
    """Materialize a complete (all four required files) skill bundle on disk."""
    skill_dir = folder / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Baked bundle for autostart tests\n---\n"
        f"# {name}\n"
    )
    (skill_dir / "schema.json").write_text(
        json.dumps({"type": "object", "properties": {}})
    )
    (skill_dir / "db.json").write_text(json.dumps({}))
    (skill_dir / "api.json").write_text(json.dumps(MINIMAL_SPEC))
    if mtime is not None:
        # most_recent_complete_skill() ranks by SKILL.md mtime.
        os.utime(skill_dir / "SKILL.md", (mtime, mtime))


async def _fake_generate_writing_artifacts(
    *,
    openapi_spec: dict[str, Any],
    simulation_name: str,
    skills_folder: Path,
    progress_cb: Any = None,
) -> Path:
    """Stand-in for SkillGenerator.generate_skill: write a bundle, skip the LLM."""
    skill_dir = Path(skills_folder) / simulation_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {simulation_name}\ndescription: Generated\n---\n# skill\n"
    )
    (skill_dir / "schema.json").write_text(
        json.dumps({"type": "object", "properties": {}})
    )
    (skill_dir / "db.json").write_text(json.dumps({}))
    (skill_dir / "api.json").write_text(json.dumps(openapi_spec))
    return skill_dir / "SKILL.md"


def _write_base_config(path: Path) -> None:
    config = {
        "llm": {
            "provider": "openai",
            "skill_generation_model": "gpt-4",
            "simulation_model": "gpt-4",
            "temperature": 0,
        },
        # Placeholder — HARNESS_SKILLS_FOLDER env override points at the temp dir,
        # which also exercises the env-driven durable-location path.
        "skills": {"folder": "./skills"},
        "sessions": {
            "max_messages": 100,
            "idle_timeout_seconds": 3600,
            "max_concurrent_queue_depth": 8,
        },
        "mcp": {"transport": "sse"},
        # Autostart defaults off; these boot tests exercise the enabled paths.
        "startup": {"autostart_enabled": True},
    }
    path.write_text(yaml.safe_dump(config))


@contextmanager
def booted_harness(
    tmp_path: Path,
    skills_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    autostart: str | None = None,
) -> Iterator[TestClient]:
    """Reload the app against ``skills_folder`` and run its lifespan (autostart).

    Config is read at import time, so we set env, reset the cached singletons,
    then reload ``main`` so ``load_config`` + ``apply_env_overrides`` pick up the
    temp skills folder (via HARNESS_SKILLS_FOLDER) and optional autostart name.
    """
    cfg_path = tmp_path / "harness.yaml"
    _write_base_config(cfg_path)

    monkeypatch.setenv("HARNESS_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_SKILLS_FOLDER", str(skills_folder))
    if autostart is not None:
        monkeypatch.setenv("HARNESS_AUTOSTART_SIMULATION", autostart)
    else:
        monkeypatch.delenv("HARNESS_AUTOSTART_SIMULATION", raising=False)

    import simulation_harness.api.dependencies as deps
    import simulation_harness.main as main

    # Fresh singletons so autostart runs against this test's config/volume.
    deps._simulation_host = None
    deps._skill_registry = None
    importlib.reload(main)

    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        # Leave clean state for other integration tests.
        deps._simulation_host = None
        deps._skill_registry = None


def test_empty_volume_boots_idle_and_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty volume → healthy, idle pod (no autostart) that still accepts a spec."""
    skills = tmp_path / "skills-store"
    skills.mkdir()

    with booted_harness(tmp_path, skills, monkeypatch) as client:
        assert client.get("/healthz").status_code == 200

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # Nothing was autostarted.
        assert client.get("/api/v1/simulation").status_code == 404

        # The idle pod accepts POST /api/v1/simulation and reaches ready.
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = _fake_generate_writing_artifacts
            resp = client.post(
                "/api/v1/simulation",
                json={"openapi_spec": MINIMAL_SPEC, "regenerate_skill": False},
            )
            assert resp.status_code == 202
            final = poll_until_ready(client, timeout=30.0)
        assert final["status"] == "ready", f"expected ready, got: {final}"


def test_populated_volume_autostarts_without_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Populated volume (one bundle) → autostart to ready, no skill generation."""
    skills = tmp_path / "skills-store"
    skills.mkdir()
    _bake_skill(skills, "petstore")

    with patch(
        "simulation_harness.skills.generator.SkillGenerator.generate_skill",
        new_callable=AsyncMock,
    ) as mock_gen:
        with booted_harness(tmp_path, skills, monkeypatch) as client:
            final = poll_until_ready(client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"
            assert final["name"] == "petstore"
            assert client.get("/readyz").status_code == 200

    # No regeneration: the baked bundle was started as-is.
    mock_gen.assert_not_called()


def test_autostart_env_selects_named_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARNESS_AUTOSTART_SIMULATION starts the named bundle, over the most recent."""
    skills = tmp_path / "skills-store"
    skills.mkdir()
    _bake_skill(skills, "alpha", mtime=1_000_000)
    _bake_skill(skills, "beta", mtime=2_000_000)  # newer, but not selected

    with booted_harness(tmp_path, skills, monkeypatch, autostart="alpha") as client:
        final = poll_until_ready(client, timeout=30.0)
        assert final["status"] == "ready", f"expected ready, got: {final}"
        assert final["name"] == "alpha"


def test_multiple_bundles_unset_autostarts_most_recent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset autostart + >1 bundle → the most-recent bundle starts."""
    skills = tmp_path / "skills-store"
    skills.mkdir()
    _bake_skill(skills, "older", mtime=1_000_000)
    _bake_skill(skills, "newer", mtime=2_000_000)

    with booted_harness(tmp_path, skills, monkeypatch) as client:
        final = poll_until_ready(client, timeout=30.0)
        assert final["status"] == "ready", f"expected ready, got: {final}"
        assert final["name"] == "newer"


def test_disabled_flag_ignores_baked_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """autostart_enabled=false → boot idle even with a complete baked skill."""
    skills = tmp_path / "skills-store"
    skills.mkdir()
    _bake_skill(skills, "petstore")

    monkeypatch.setenv("HARNESS_AUTOSTART_ENABLED", "false")
    with booted_harness(tmp_path, skills, monkeypatch) as client:
        assert client.get("/healthz").status_code == 200

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # Skill present, but the flag forced an idle boot.
        assert client.get("/api/v1/simulation").status_code == 404
