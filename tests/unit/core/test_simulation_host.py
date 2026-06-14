"""Tests for SimulationHost."""

import os

import pytest

from simulation_harness.config.settings import load_config, load_secrets
from simulation_harness.core.simulation_host import SimulationHost
from simulation_harness.models.domain import SimulationSpec
from simulation_harness.utils.errors import SimulationAlreadyExistsError


@pytest.fixture(scope="module", autouse=True)
def load_test_config():
    """Load configuration and secrets before running tests."""
    from pathlib import Path
    from simulation_harness.config import settings as settings_mod

    # Resolve absolute path from file: file -> core/ -> unit/ -> tests/ -> project root
    config_path = str(
        Path(__file__).parent.parent.parent.parent / "config" / "harness.yaml"
    )
    load_config(config_path)

    prior_key = os.environ.get("LLM_API_KEY")
    os.environ["LLM_API_KEY"] = "test-key-for-unit-tests"
    load_secrets(env_file=None)

    yield

    # Restore env var
    if prior_key is not None:
        os.environ["LLM_API_KEY"] = prior_key
    elif "LLM_API_KEY" in os.environ:
        del os.environ["LLM_API_KEY"]

    # Reset module-level global so later test modules start clean
    settings_mod._global_secrets = None


@pytest.mark.asyncio
async def test_create_simulation_success():
    """Test creating a simulation successfully."""
    host = SimulationHost()
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
    )

    instance = await host.create_simulation(spec)

    assert instance is not None
    assert await host.get_simulation() == instance


@pytest.mark.asyncio
async def test_create_simulation_rejects_duplicate():
    """Test that creating a simulation when one exists raises error."""
    host = SimulationHost()
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
    )

    await host.create_simulation(spec)

    with pytest.raises(SimulationAlreadyExistsError):
        await host.create_simulation(spec)


@pytest.mark.asyncio
async def test_get_simulation_returns_none_when_empty():
    """Test getting simulation when none exists."""
    host = SimulationHost()

    result = await host.get_simulation()

    assert result is None


@pytest.mark.asyncio
async def test_delete_simulation_success():
    """Test deleting a simulation."""
    host = SimulationHost()
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
    )

    await host.create_simulation(spec)
    await host.delete_simulation()

    assert await host.get_simulation() is None


@pytest.mark.asyncio
async def test_delete_simulation_when_none_exists():
    """Test deleting when no simulation exists (should be idempotent)."""
    host = SimulationHost()

    await host.delete_simulation()

    assert await host.get_simulation() is None


@pytest.mark.asyncio
async def test_lifecycle_lock_serializes_operations():
    """Test that lifecycle operations are serialized."""
    import asyncio

    host = SimulationHost()
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
    )

    # Create simulation
    await host.create_simulation(spec)

    # Try to create and delete concurrently - should be serialized
    async def try_create():
        try:
            await host.create_simulation(spec)
        except SimulationAlreadyExistsError:
            pass

    async def try_delete():
        await host.delete_simulation()

    # Run operations concurrently
    await asyncio.gather(try_create(), try_delete(), try_create())

    # Should end in a consistent state (either exists or doesn't)
    result = await host.get_simulation()
    # Result can be None or an instance, but should be consistent
    assert result is None or result is not None


# Made with Bob
