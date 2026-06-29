from simulation_harness.config.models import GenerationConfig


def test_generation_config_scenario_defaults():
    cfg = GenerationConfig()
    assert cfg.scenarios_enabled is True
    assert cfg.scenarios_count == 5
    assert cfg.scenarios.temperature == 0.4
    assert cfg.scenarios.max_tokens == 3000
