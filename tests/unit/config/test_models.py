import pytest

from simulation_harness.config.models import GenerationConfig, StartupConfig


def test_generation_config_scenario_defaults() -> None:
    cfg = GenerationConfig()
    assert cfg.scenarios_enabled is True
    assert cfg.scenarios_count == 5
    assert cfg.scenarios.temperature == 0.4
    assert cfg.scenarios.max_tokens == 3000


def test_startup_autostart_enabled_defaults_false() -> None:
    assert StartupConfig().autostart_enabled is False


def test_startup_autostart_enabled_accepts_true() -> None:
    assert StartupConfig(autostart_enabled=True).autostart_enabled is True


class TestSimulationConfig:
    def test_defaults_to_generative_report(self) -> None:
        from simulation_harness.config.models import SimulationConfig

        cfg = SimulationConfig()
        assert cfg.fidelity == "generative"
        assert cfg.strict_grounding == "report"

    def test_rejects_unknown_fidelity(self) -> None:
        from pydantic import ValidationError

        from simulation_harness.config.models import SimulationConfig

        with pytest.raises(ValidationError):
            SimulationConfig(fidelity="loose")  # type: ignore[arg-type]

    def test_rejects_unknown_key(self) -> None:
        from pydantic import ValidationError

        from simulation_harness.config.models import SimulationConfig

        with pytest.raises(ValidationError):
            SimulationConfig(fidellity="strict")  # type: ignore[call-arg]

    def test_harness_config_has_simulation_section_by_default(self) -> None:
        from simulation_harness.config.models import HarnessConfig

        cfg = HarnessConfig(
            llm={
                "provider": "openai",
                "skill_generation_model": "m",
                "simulation_model": "m",
            },
            skills={"folder": "./skills-store"},
            sessions={"max_messages": 10, "idle_timeout_seconds": 60},
            mcp={"transport": "sse"},
        )
        assert cfg.simulation.fidelity == "generative"
