"""Tests for the offline setup CLI (fail-fast paths, no LLM)."""

import json
from pathlib import Path

import pytest

from simulation_harness.setup_cli import main


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "acme", "version": "1"},
        "paths": {},
    }
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return p


def test_main_exits_nonzero_on_missing_file(tmp_path: Path) -> None:
    rc = main([str(tmp_path / "nope.json")])
    assert rc != 0


def test_main_exits_nonzero_on_invalid_spec(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "an openapi spec"}))
    rc = main([str(bad)])
    assert rc != 0
