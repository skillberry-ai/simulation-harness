"""Guard the determinism script's request payload against the API it posts to.

``scripts/check-generation-determinism.sh`` drives repeated generation over HTTP.
Its create payload once said ``regenerate: true`` while the field on
:class:`CreateSimulationRequest` is ``regenerate_skill`` -- and because that model
declares no ``model_config``, pydantic's default ``extra="ignore"`` dropped the
unknown key instead of rejecting it. ``regenerate_skill`` stayed ``False``, every
run after the first reused the first run's artifacts, and the script reported an
identical contract having generated exactly once.

Nothing in the Python test suite could see that, so these tests read the script
itself. The precedent is ``test_shipped_harness_yaml_stage_temperatures``, which
likewise asserts against a file in the repo root rather than an import.
"""

import re
from pathlib import Path

import pytest

from simulation_harness.models.requests import CreateSimulationRequest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check-generation-determinism.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    assert SCRIPT.is_file(), f"determinism script missing at {SCRIPT}"
    return SCRIPT.read_text()


def _payload_keys(text: str) -> set[str]:
    """Keys from the script's jq-built create payload.

    Matches the jq object literal that carries ``openapi_spec`` -- the create
    body -- rather than every brace in the file.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("'{") and "openapi_spec" in stripped:
            return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped))
    raise AssertionError("no jq create payload found in the determinism script")


def test_create_payload_keys_all_exist_on_the_request_model(script_text: str) -> None:
    """Every key the script sends must be a real field, not silently ignored."""
    unknown = _payload_keys(script_text) - set(CreateSimulationRequest.model_fields)
    assert not unknown, (
        f"{SCRIPT.name} posts key(s) {sorted(unknown)} that CreateSimulationRequest "
        "does not declare. pydantic's default extra='ignore' drops them silently, "
        "so the request still succeeds with the field left at its default."
    )


def test_create_payload_forces_regeneration(script_text: str) -> None:
    """Reuse would make runs 2..N no-ops and the comparison vacuous."""
    assert "regenerate_skill" in _payload_keys(script_text), (
        f"{SCRIPT.name} must send regenerate_skill so each run regenerates; "
        "without it the harness reuses run 1's skill and the check compares "
        "those artifacts against themselves."
    )


def test_script_asserts_the_artifact_was_rewritten(script_text: str) -> None:
    """A reuse guard must survive independently of the flag's spelling."""
    assert "mtime_before" in script_text and "mtime_after" in script_text, (
        f"{SCRIPT.name} must verify schema.json's mtime advanced on each run, so "
        "that a future rename of the regenerate flag fails loudly instead of "
        "silently comparing one generation against itself."
    )
