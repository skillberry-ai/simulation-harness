"""Integration: per-simulation skills are discoverable through the backend."""

import shutil

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import _list_skills

from simulation_harness.agent.skill_backend import build_skill_sources
from pathlib import Path


def test_active_simulation_skill_is_discovered_and_isolated(tmp_path: Path) -> None:
    skill_dir = tmp_path / "petstore"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: petstore\n"
        "description: Simulate the Pet Store API.\n---\n"
        "# Pet Store Simulation\n\nOperation detail here.\n"
    )
    # A sibling simulation that must NOT leak into this session.
    other = tmp_path / "weather"
    other.mkdir()
    (other / "SKILL.md").write_text(
        "---\nname: weather\ndescription: other sim\n---\n# Weather\n"
    )

    root_dir, sources = build_skill_sources(skill_dir)
    try:
        backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

        skills = _list_skills(backend, sources[0])
        names = [s["name"] for s in skills]

        # Exactly one skill, and it's this simulation's — the sibling is invisible.
        assert names == ["petstore"]

        # The advertised path resolves to the real SKILL.md body.
        skill = skills[0]
        response = backend.download_files([skill["path"]])[0]
        assert response.error is None
        assert response.content is not None
        assert "Pet Store Simulation" in response.content.decode()
    finally:
        shutil.rmtree(root_dir, ignore_errors=True)
