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
