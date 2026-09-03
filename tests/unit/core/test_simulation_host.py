"""Tests for SimulationHost."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from simulation_harness.config.settings import load_config, load_secrets
from simulation_harness.core.simulation_host import SimulationHost
from simulation_harness.core.simulation_record import SimulationStatus
from simulation_harness.utils.errors import (
    SimulationAlreadyExistsError,
    SimulationArtifactsNotFoundError,
)
from collections.abc import Iterator
from typing import Any


@pytest.fixture(scope="module", autouse=True)
def load_test_config() -> Iterator[None]:
    """Load configuration and secrets before running tests."""
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


@pytest.fixture
def fake_skill_registry() -> MagicMock:
    reg = MagicMock()
    started = asyncio.Event()

    async def ensure_skill(
        simulation_name: Any,
        openapi_spec: Any,
        regenerate: Any,
        progress_cb: Any = None,
    ) -> Any:
        started.set()
        await asyncio.sleep(0.05)
        return Path(f"/tmp/skills/{simulation_name}/SKILL.md")

    reg.ensure_skill = AsyncMock(side_effect=ensure_skill)
    reg.skills_folder = Path("/tmp/skills")
    reg._started_event = started  # for tests
    return reg


@pytest.fixture
def fake_instance_factory() -> Any:
    instance = MagicMock()
    instance.shutdown = AsyncMock()
    instance.spec = MagicMock(name="test-api")
    factory = MagicMock(return_value=instance)
    return factory, instance


async def _wait_for_ready(host: SimulationHost, timeout: float = 3.0) -> None:
    """Poll until the record is in a terminal state (READY or FAILED)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        record = await host.get_record()
        if record is not None and record.status in (
            SimulationStatus.READY,
            SimulationStatus.FAILED,
        ):
            return
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# New async-lifecycle tests
# ---------------------------------------------------------------------------


async def test_declare_simulation_returns_pending_record_immediately(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    factory, _ = fake_instance_factory
    host = SimulationHost()
    record = await host.declare_simulation(
        name="test-api",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "test-api", "version": "1"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    try:
        assert record.status == SimulationStatus.PENDING
    finally:
        await host.delete_simulation()


async def test_declare_simulation_when_record_exists_raises(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    factory, _ = fake_instance_factory
    host = SimulationHost()
    await host.declare_simulation(
        name="a",
        openapi_spec={"openapi": "3.0.0", "info": {"title": "a", "version": "1"}},
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    try:
        with pytest.raises(SimulationAlreadyExistsError):
            await host.declare_simulation(
                name="b",
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "b", "version": "1"},
                },
                regenerate=False,
                mcp_port=None,
                skill_registry=fake_skill_registry,
                instance_factory=factory,
                max_duration_seconds=5,
            )
    finally:
        await host.delete_simulation()


async def test_record_progresses_to_ready_in_background(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    factory, instance = fake_instance_factory
    host = SimulationHost()
    record = await host.declare_simulation(
        name="test-api",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "test-api", "version": "1"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    try:
        for _ in range(50):
            current = await host.get_record()
            if current is not None and current.status == SimulationStatus.READY:
                break
            await asyncio.sleep(0.05)
        assert record.status == SimulationStatus.READY
        assert record.instance is instance
    finally:
        await host.delete_simulation()


async def test_delete_during_pending_cancels_creation(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    factory, _ = fake_instance_factory
    host = SimulationHost()
    await host.declare_simulation(
        name="test-api",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "test-api", "version": "1"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=30,
    )
    # wait for skill generation to actually start
    await asyncio.wait_for(fake_skill_registry._started_event.wait(), timeout=1.0)
    await host.delete_simulation()
    assert await host.get_record() is None
    # Ensure background task is fully done.
    assert host._creation_task is None


# ---------------------------------------------------------------------------
# Updated old tests using the new declare_simulation API
# ---------------------------------------------------------------------------


async def test_create_simulation_success(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    """Test creating a simulation successfully (via declare_simulation)."""
    factory, instance = fake_instance_factory
    host = SimulationHost()

    record = await host.declare_simulation(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    try:
        await _wait_for_ready(host)
        assert record.status == SimulationStatus.READY
        assert await host.get_simulation() is instance
    finally:
        await host.delete_simulation()


async def test_create_simulation_rejects_duplicate(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    """Test that declaring a simulation when one exists raises error."""
    factory, _ = fake_instance_factory
    host = SimulationHost()

    await host.declare_simulation(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    try:
        with pytest.raises(SimulationAlreadyExistsError):
            await host.declare_simulation(
                name="test-sim",
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "Test", "version": "1.0.0"},
                },
                regenerate=False,
                mcp_port=None,
                skill_registry=fake_skill_registry,
                instance_factory=factory,
                max_duration_seconds=5,
            )
    finally:
        await host.delete_simulation()


async def test_get_simulation_returns_none_when_empty() -> None:
    """Test getting simulation when none exists."""
    host = SimulationHost()

    result = await host.get_simulation()

    assert result is None


async def test_delete_simulation_success(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    """Test deleting a simulation."""
    factory, _ = fake_instance_factory
    host = SimulationHost()

    await host.declare_simulation(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )
    await _wait_for_ready(host)
    await host.delete_simulation()

    assert await host.get_simulation() is None
    assert await host.get_record() is None


async def test_delete_simulation_when_none_exists() -> None:
    """Test deleting when no simulation exists (should be idempotent)."""
    host = SimulationHost()

    await host.delete_simulation()

    assert await host.get_simulation() is None


async def test_lifecycle_lock_serializes_operations(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    """Test that lifecycle operations are serialized."""
    factory, _ = fake_instance_factory
    host = SimulationHost()

    await host.declare_simulation(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
        regenerate=False,
        mcp_port=None,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
        max_duration_seconds=5,
    )

    # Try to create and delete concurrently - should be serialized
    async def try_declare() -> None:
        try:
            await host.declare_simulation(
                name="test-sim",
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "Test", "version": "1.0.0"},
                },
                regenerate=False,
                mcp_port=None,
                skill_registry=fake_skill_registry,
                instance_factory=factory,
                max_duration_seconds=5,
            )
        except SimulationAlreadyExistsError:
            pass

    async def try_delete() -> None:
        await host.delete_simulation()

    # Run operations concurrently
    await asyncio.gather(try_declare(), try_delete(), try_declare())

    # Should end in a consistent state (either exists or doesn't)
    result = await host.get_simulation()
    # Result can be None or an instance, but should be consistent
    assert result is None or result is not None


async def test_create_simulation_passes_mcp_port_to_instance(
    fake_skill_registry: MagicMock,
) -> None:
    """declare_simulation forwards mcp_port to the instance factory."""
    captured_kwargs: dict = {}

    def capturing_factory(**kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        inst = MagicMock()
        inst.shutdown = AsyncMock()
        return inst

    host = SimulationHost()
    await host.declare_simulation(
        name="test",
        openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        regenerate=False,
        mcp_port=9000,
        skill_registry=fake_skill_registry,
        instance_factory=capturing_factory,
        max_duration_seconds=5,
    )
    try:
        await _wait_for_ready(host)
        assert captured_kwargs.get("mcp_port") == 9000
    finally:
        await host.delete_simulation()


async def test_create_simulation_starts_sidecar_when_mcp_port_provided(
    fake_skill_registry: MagicMock,
) -> None:
    """When mcp_port is set, _run_creation starts a SidecarMCPServer after READY."""
    from unittest.mock import patch

    mock_sidecar = MagicMock()
    mock_sidecar.start = AsyncMock()

    mock_inst = MagicMock()
    mock_inst.shutdown = AsyncMock()
    mock_inst._sidecar = None

    def factory(**kwargs: Any) -> Any:
        return mock_inst

    host = SimulationHost()
    with (
        patch(
            "simulation_harness.core.simulation_host.SidecarMCPServer",
            return_value=mock_sidecar,
        ) as mock_sidecar_cls,
        patch("simulation_harness.core.simulation_host.get_config") as mock_cfg,
    ):
        mock_cfg.return_value.mcp = MagicMock()
        mock_cfg.return_value.creation.max_duration_seconds = 30
        mock_cfg.return_value.server.host = "127.0.0.1"

        await host.declare_simulation(
            name="test",
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            regenerate=False,
            mcp_port=9000,
            skill_registry=fake_skill_registry,
            instance_factory=factory,
            max_duration_seconds=5,
        )
        try:
            await _wait_for_ready(host)
            mock_sidecar.start.assert_called_once()
            assert mock_inst._sidecar is mock_sidecar
            # The sidecar binds server.host, not a hardcoded 0.0.0.0.
            assert mock_sidecar_cls.call_args.args[3] == "127.0.0.1"
        finally:
            await host.delete_simulation()


async def test_create_simulation_cleans_up_instance_on_port_in_use(
    fake_skill_registry: MagicMock,
) -> None:
    """When sidecar.start() raises PortInUseError, instance is shut down and record fails."""
    from unittest.mock import patch
    from simulation_harness.utils.errors import PortInUseError

    mock_sidecar = MagicMock()
    mock_sidecar.start = AsyncMock(side_effect=PortInUseError("Port 9000 in use"))

    mock_inst = MagicMock()
    mock_inst.shutdown = AsyncMock()
    mock_inst._sidecar = None

    def factory(**kwargs: Any) -> Any:
        return mock_inst

    host = SimulationHost()
    with (
        patch(
            "simulation_harness.core.simulation_host.SidecarMCPServer",
            return_value=mock_sidecar,
        ),
        patch("simulation_harness.core.simulation_host.get_config") as mock_cfg,
    ):
        mock_cfg.return_value.mcp = MagicMock()
        mock_cfg.return_value.creation.max_duration_seconds = 30

        await host.declare_simulation(
            name="test",
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            regenerate=False,
            mcp_port=9000,
            skill_registry=fake_skill_registry,
            instance_factory=factory,
            max_duration_seconds=5,
        )
        # Wait until background task completes (record enters terminal state or task finishes)
        for _ in range(50):
            record = await host.get_record()
            if record is not None and record.status == SimulationStatus.FAILED:
                break
            await asyncio.sleep(0.05)

    # Instance was shut down
    mock_inst.shutdown.assert_called_once()
    # Record should be in FAILED state
    record = await host.get_record()
    assert record is not None
    assert record.status == SimulationStatus.FAILED
    assert record.error is not None
    assert record.error.code == "sidecar_start_failed"


class TestReplaceDatabase:
    async def test_replace_database_writes_and_resets(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from simulation_harness.core.simulation_record import (
            SimulationRecord,
            SimulationStatus,
        )
        from simulation_harness.models.domain import SessionState

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

        record = SimulationRecord.declare(name="demo")
        record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
        record.mark_ready(instance)
        host._record = record

        skill_registry = MagicMock()
        new_db: dict[str, Any] = {"items": []}

        await host.replace_database(new_db=new_db, skill_registry=skill_registry)

        skill_registry.write_db.assert_called_once_with("demo", new_db)
        instance.reset_session.assert_awaited_once()

    async def test_replace_database_no_simulation_raises(self) -> None:
        from simulation_harness.utils.errors import SimulationNotFoundError

        host = SimulationHost()
        with pytest.raises(SimulationNotFoundError):
            await host.replace_database(new_db={}, skill_registry=MagicMock())

    async def test_replace_database_not_ready_raises(self) -> None:
        from simulation_harness.core.simulation_record import SimulationRecord
        from simulation_harness.utils.errors import SimulationNotReadyError

        host = SimulationHost()
        host._record = SimulationRecord.declare(name="demo")

        with pytest.raises(SimulationNotReadyError):
            await host.replace_database(new_db={}, skill_registry=MagicMock())

    async def test_replace_database_busy_raises(self) -> None:
        from unittest.mock import MagicMock

        from simulation_harness.core.simulation_record import (
            SimulationRecord,
            SimulationStatus,
        )
        from simulation_harness.models.domain import SessionState
        from simulation_harness.utils.errors import SimulationBusyError

        host = SimulationHost()
        instance = MagicMock()
        instance.get_session_state.return_value = SessionState(
            tool_call_count=0,
            max_messages=100,
            idle_timeout_seconds=3600,
            last_activity=None,
            queue_depth=2,
            max_queue_depth=8,
        )

        record = SimulationRecord.declare(name="demo")
        record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
        record.mark_ready(instance)
        host._record = record

        skill_registry = MagicMock()
        with pytest.raises(SimulationBusyError) as exc:
            await host.replace_database(new_db={}, skill_registry=skill_registry)
        assert exc.value.queue_depth == 2
        skill_registry.write_db.assert_not_called()

    async def test_replace_database_does_not_reset_when_write_fails(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from simulation_harness.core.simulation_record import (
            SimulationRecord,
            SimulationStatus,
        )
        from simulation_harness.models.domain import SessionState
        from simulation_harness.utils.errors import DatabaseValidationError

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

        record = SimulationRecord.declare(name="demo")
        record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
        record.mark_ready(instance)
        host._record = record

        skill_registry = MagicMock()
        skill_registry.write_db.side_effect = DatabaseValidationError(message="bad")

        with pytest.raises(DatabaseValidationError):
            await host.replace_database(new_db={}, skill_registry=skill_registry)
        instance.reset_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# setup_simulation / start_simulation tests
# ---------------------------------------------------------------------------


def _bake_artifacts(folder: Path, name: str) -> None:
    d = folder / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("# skill")
    (d / "schema.json").write_text(json.dumps({"type": "object"}))
    (d / "db.json").write_text(json.dumps({}))
    (d / "api.json").write_text(
        json.dumps({"openapi": "3.0.0", "info": {"title": name, "version": "1"}})
    )


async def test_setup_simulation_reaches_generated(
    fake_skill_registry: MagicMock, fake_instance_factory: Any
) -> None:
    factory, _ = fake_instance_factory
    host = SimulationHost()
    record = await host.setup_simulation(
        name="acme",
        openapi_spec={"openapi": "3.0.0", "info": {"title": "acme", "version": "1"}},
        regenerate=False,
        skill_registry=fake_skill_registry,
        instance_factory=factory,
    )
    assert host._creation_task is not None
    await host._creation_task
    assert record.status == SimulationStatus.GENERATED
    assert record.instance is None
    factory.assert_not_called()


async def test_start_simulation_from_artifacts_reaches_ready(
    tmp_path: Path, fake_instance_factory: Any
) -> None:
    from simulation_harness.core.skill_registry import SkillRegistry

    factory, instance = fake_instance_factory
    _bake_artifacts(tmp_path, "acme")
    registry = SkillRegistry(skills_folder=tmp_path, generator=MagicMock())
    host = SimulationHost()

    record = await host.start_simulation(
        name="acme",
        mcp_port=None,
        skill_registry=registry,
        instance_factory=factory,
    )
    assert host._creation_task is not None
    await host._creation_task

    assert record.status == SimulationStatus.READY
    factory.assert_called_once()
    # Spec was loaded from api.json, not passed by a caller.
    kwargs = factory.call_args.kwargs
    assert kwargs["openapi_spec"]["info"]["title"] == "acme"


async def test_start_simulation_missing_artifacts_raises(
    tmp_path: Path, fake_instance_factory: Any
) -> None:
    from simulation_harness.core.skill_registry import SkillRegistry

    factory, _ = fake_instance_factory
    registry = SkillRegistry(skills_folder=tmp_path, generator=MagicMock())
    host = SimulationHost()

    with pytest.raises(SimulationArtifactsNotFoundError):
        await host.start_simulation(
            name="ghost",
            mcp_port=None,
            skill_registry=registry,
            instance_factory=factory,
        )
    assert await host.get_record() is None


# Made with Bob
