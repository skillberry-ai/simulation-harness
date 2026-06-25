"""Shared fixtures for state-layer tests.

These tests load a real schema/seed pair. The fixture lives under the
git-tracked ``tests/fixtures`` tree (resolved relative to this file, not the
process working directory) so the suite is hermetic and does not depend on the
gitignored ``skills-store`` runtime folder.
"""

from pathlib import Path

import pytest

# tests/unit/state/conftest.py -> repo_root/tests/fixtures/...
_FIXTURE_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "restaurant-reservation-api"
)


@pytest.fixture
def skill_dir() -> Path:
    """Path to the restaurant reservation fixture skill (schema.json + db.json)."""
    return _FIXTURE_SKILL_DIR
