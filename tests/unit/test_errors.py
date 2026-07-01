"""Tests for domain exception classes."""

from simulation_harness.utils.errors import SimulationArtifactsNotFoundError


def test_artifacts_not_found_carries_name_and_missing() -> None:
    err = SimulationArtifactsNotFoundError(name="acme", missing=["db.json"])
    assert err.name == "acme"
    assert err.missing == ["db.json"]
    assert "acme" in str(err)
    assert "db.json" in str(err)
