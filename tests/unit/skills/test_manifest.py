"""Tests for the skill provenance manifest builder."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from simulation_harness.skills.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    build_manifest,
    canonical_spec_digest,
)

# sha256 of the exact byte strings written by the `artifacts` fixture below.
# Hardcoded (not recomputed in the test) so the test proves we hash file
# *content* rather than, say, the path or an in-memory re-serialization.
DIGESTS = {
    "SKILL.md": "31ca6c61ca3fcc54029a62bd082448b88718b913d24e195794969dd2d123b990",
    "schema.json": "ff419ebbeba438f66900abe77818ce940702bdfe70fa173cb94beecee8d3f112",
    "db.json": "eeb85c2675888473ec64b7580aa0c76c6fd6b2bd51828870286ef202ad89dae2",
    "api.json": "12c381d0f43620051c2a3f658264d20ff1459a0e2a8de1035ce2d02e8a0f78ac",
    "scenarios.json": "7a064075afc833b88eacf77efdc2c32cc3e4d83a5b65f0b40c39d36c6a5e8ccd",
}
SIZES = {
    "SKILL.md": 7,
    "schema.json": 18,
    "db.json": 13,
    "api.json": 20,
    "scenarios.json": 17,
}
CONTENTS = {
    "SKILL.md": "# Demo\n",
    "schema.json": '{"type": "object"}',
    "db.json": '{"items": []}',
    "api.json": '{"openapi": "3.0.0"}',
    "scenarios.json": '{"scenarios": []}',
}

SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Demo API", "version": "1.2.0"},
}
SPEC_DIGEST = "4e8184257775aedde02ba1d8ce5a3be4960725bd557b845d7c418f2cf70e3221"

AT = datetime(2026, 7, 30, 14, 22, 31, tzinfo=timezone.utc)


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    """A skill dir holding all five artifacts with known bytes."""
    for name, text in CONTENTS.items():
        (tmp_path / name).write_text(text)
    return tmp_path


def _build(artifact_dir: Path, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_manifest(
        artifact_dir,
        skill_name="demo",
        openapi_spec=SPEC if spec is None else spec,
        model="gpt-4",
        harness_version="0.1.0",
        generated_at=AT,
    )


def test_files_carry_known_digests_and_sizes(artifacts: Path) -> None:
    files = _build(artifacts)["files"]

    for name, digest in DIGESTS.items():
        assert files[name]["digest"] == {"sha256": digest}, name
        assert files[name]["size"] == SIZES[name], name


def test_records_generation_identity(artifacts: Path) -> None:
    manifest = _build(artifacts)

    assert manifest["manifestVersion"] == MANIFEST_VERSION
    assert manifest["skill"] == {
        "name": "demo",
        "generatedAt": "2026-07-30T14:22:31Z",
    }
    assert manifest["generator"] == {"harnessVersion": "0.1.0", "model": "gpt-4"}


def test_generated_at_normalises_non_utc_input(artifacts: Path) -> None:
    """A non-UTC aware datetime is converted, not rendered with its own offset."""
    from datetime import timedelta

    east = timezone(timedelta(hours=2))
    manifest = build_manifest(
        artifacts,
        skill_name="demo",
        openapi_spec=SPEC,
        model="gpt-4",
        harness_version="0.1.0",
        generated_at=datetime(2026, 7, 30, 16, 22, 31, tzinfo=east),
    )

    assert manifest["skill"]["generatedAt"] == "2026-07-30T14:22:31Z"


def test_source_records_spec_title_version_and_canonical_digest(
    artifacts: Path,
) -> None:
    source = _build(artifacts)["source"]["openapi"]

    assert source["title"] == "Demo API"
    assert source["version"] == "1.2.0"
    assert source["canonicalDigest"] == {"sha256": SPEC_DIGEST}


def test_scenarios_omitted_when_absent(artifacts: Path) -> None:
    (artifacts / "scenarios.json").unlink()

    files = _build(artifacts)["files"]

    assert "scenarios.json" not in files
    assert set(files) == {"SKILL.md", "schema.json", "db.json", "api.json"}


def test_manifest_never_lists_itself(artifacts: Path) -> None:
    """A pre-existing manifest.json is not a subject — it cannot digest itself."""
    (artifacts / MANIFEST_FILENAME).write_text("{}")

    assert MANIFEST_FILENAME not in _build(artifacts)["files"]


def test_canonical_digest_ignores_key_order_and_indentation() -> None:
    reordered: dict[str, Any] = {
        "info": {"version": "1.2.0", "title": "Demo API"},
        "openapi": "3.0.0",
    }

    assert canonical_spec_digest(reordered) == canonical_spec_digest(SPEC)
    assert canonical_spec_digest(json.loads(json.dumps(SPEC, indent=4))) == SPEC_DIGEST


def test_canonical_digest_changes_when_a_value_changes() -> None:
    changed: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Demo API", "version": "1.2.1"},
    }

    assert canonical_spec_digest(changed) != canonical_spec_digest(SPEC)


def test_spec_without_info_omits_title_and_version(artifacts: Path) -> None:
    """A minimal or malformed spec must not fail manifest generation."""
    source = _build(artifacts, {"openapi": "3.0.0"})["source"]["openapi"]

    assert "title" not in source
    assert "version" not in source
    assert "sha256" in source["canonicalDigest"]


def test_non_dict_info_is_tolerated(artifacts: Path) -> None:
    source = _build(artifacts, {"openapi": "3.0.0", "info": "nonsense"})["source"][
        "openapi"
    ]

    assert "title" not in source
    assert "version" not in source


def test_manifest_is_json_serialisable(artifacts: Path) -> None:
    assert json.loads(json.dumps(_build(artifacts))) == _build(artifacts)
