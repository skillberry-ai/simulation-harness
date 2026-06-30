"""Integration test fixtures and helpers."""

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from collections.abc import Iterator

# Lifecycle/MCP integration tests mock skill generation to return a SKILL.md
# path without creating the directory on disk. Agent init then copies that
# directory (agent/skill_backend.py:build_skill_sources), so the path must be a
# real, valid skill dir. These are the paths those mocks return.
_MOCKED_SKILL_DIRS = ("/tmp/fake-skill", "/tmp/test-api")


def _write_valid_skill(skill_dir: Path) -> None:
    """Materialize a minimal but valid skill directory at ``skill_dir``."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-api\ndescription: Test skill for integration fixtures\n---\n"
        "# Test skill\n"
    )
    # An empty store satisfies the schema/seed loader (state/loader.py).
    (skill_dir / "schema.json").write_text(
        json.dumps({"type": "object", "properties": {}})
    )
    (skill_dir / "db.json").write_text(json.dumps({}))


@pytest.fixture(autouse=True)
def mocked_skill_dirs() -> Iterator[None]:
    """Create the skill dirs that generate_skill mocks point at, then clean up.

    The integration tests patch ``SkillGenerator.generate_skill`` to return e.g.
    ``Path("/tmp/fake-skill/SKILL.md")``. Without the directory actually
    existing, agent init fails with ``instance_init_failed`` (FileNotFoundError)
    and the simulation never reaches ``ready``.
    """
    for path in _MOCKED_SKILL_DIRS:
        skill_dir = Path(path)
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        _write_valid_skill(skill_dir)
    try:
        yield
    finally:
        for path in _MOCKED_SKILL_DIRS:
            shutil.rmtree(path, ignore_errors=True)


def poll_until_ready(client: TestClient, timeout: float = 30.0) -> dict:
    """Poll GET /api/v1/simulation until status is ready or failed.

    Returns the final response body. Raises AssertionError on timeout.
    """
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/simulation")
        if resp.status_code != 200:
            time.sleep(0.1)
            continue
        last = resp.json()
        if last["status"] in ("ready", "failed"):
            return last
        time.sleep(0.1)
    raise AssertionError(
        f"Simulation did not reach terminal status within {timeout}s; last={last}"
    )
