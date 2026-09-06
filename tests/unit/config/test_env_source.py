"""Unit tests for the single HARNESS_* lookup rule.

Precedence under test: process environment, then `.env`, then the default.
"""

from pathlib import Path

import pytest

from simulation_harness.config.env_source import (
    dotenv_snapshot,
    env_value,
    harness_env,
    resolve_config_path,
)


def _write_env(directory: Path, body: str) -> Path:
    path = directory / ".env"
    path.write_text(body)
    return path


class TestHarnessEnv:
    def test_reads_key_present_only_in_dotenv(self, tmp_path: Path) -> None:
        """The bug in #13: a HARNESS_* key in .env must be visible."""
        env_file = _write_env(tmp_path, "HARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4\n")
        assert (
            harness_env("HARNESS_LLM_SIMULATION_MODEL", env_file=str(env_file))
            == "azure/gpt-5.4"
        )

    def test_process_env_wins_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, "HARNESS_SERVER_PORT=1111\n")
        monkeypatch.setenv("HARNESS_SERVER_PORT", "2222")
        assert harness_env("HARNESS_SERVER_PORT", env_file=str(env_file)) == "2222"

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "HARNESS_SERVER_PORT=1111\n")
        assert harness_env("HARNESS_LOG_LEVEL", env_file=str(env_file)) is None

    def test_env_file_none_ignores_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests and any secrets-only deployment must be able to opt out."""
        monkeypatch.delenv("HARNESS_LOG_LEVEL", raising=False)
        _write_env(tmp_path, "HARNESS_LOG_LEVEL=DEBUG\n")
        assert harness_env("HARNESS_LOG_LEVEL", env_file=None) is None

    def test_absent_env_file_is_not_an_error(self, tmp_path: Path) -> None:
        assert harness_env("HARNESS_LOG_LEVEL", env_file=str(tmp_path / "nope")) is None

    def test_empty_process_value_is_returned_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicitly emptied var is a deliberate act, not a fall-through."""
        env_file = _write_env(tmp_path, "HARNESS_LOG_LEVEL=DEBUG\n")
        monkeypatch.setenv("HARNESS_LOG_LEVEL", "")
        assert harness_env("HARNESS_LOG_LEVEL", env_file=str(env_file)) == ""


class TestDotenvSnapshot:
    def test_snapshot_reads_all_keys(self, tmp_path: Path) -> None:
        env_file = _write_env(tmp_path, "A=1\nHARNESS_LOG_LEVEL=DEBUG\n")
        assert dotenv_snapshot(str(env_file)) == {
            "A": "1",
            "HARNESS_LOG_LEVEL": "DEBUG",
        }

    def test_snapshot_of_none_is_empty(self, tmp_path: Path) -> None:
        _write_env(tmp_path, "A=1\n")
        assert dotenv_snapshot(None) == {}

    def test_snapshot_of_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert dotenv_snapshot(str(tmp_path / "nope")) == {}

    def test_valueless_keys_are_dropped(self, tmp_path: Path) -> None:
        """`FOO` with no `=` parses to None; it must not shadow the process env."""
        env_file = _write_env(tmp_path, "HARNESS_LOG_LEVEL\n")
        assert dotenv_snapshot(str(env_file)) == {}

    def test_snapshot_is_reread_after_the_file_changes(self, tmp_path: Path) -> None:
        """No caching: a stale snapshot keyed on the relative path './.env' would
        leak between tests that chdir, which is worse than one extra file read.
        """
        env_file = _write_env(tmp_path, "HARNESS_LOG_LEVEL=DEBUG\n")
        assert dotenv_snapshot(str(env_file))["HARNESS_LOG_LEVEL"] == "DEBUG"
        _write_env(tmp_path, "HARNESS_LOG_LEVEL=INFO\n")
        assert dotenv_snapshot(str(env_file))["HARNESS_LOG_LEVEL"] == "INFO"


class TestEnvValue:
    def test_process_env_wins_over_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LOG_LEVEL", "WARNING")
        assert (
            env_value("HARNESS_LOG_LEVEL", {"HARNESS_LOG_LEVEL": "DEBUG"}) == "WARNING"
        )

    def test_snapshot_used_when_process_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HARNESS_LOG_LEVEL", raising=False)
        assert env_value("HARNESS_LOG_LEVEL", {"HARNESS_LOG_LEVEL": "DEBUG"}) == "DEBUG"


class TestResolveConfigPath:
    def test_default_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
        assert resolve_config_path(env_file=None) == "config/harness.yaml"

    def test_dotenv_value_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
        env_file = _write_env(tmp_path, "HARNESS_CONFIG_PATH=/etc/harness.yaml\n")
        assert resolve_config_path(env_file=str(env_file)) == "/etc/harness.yaml"

    def test_process_env_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, "HARNESS_CONFIG_PATH=/etc/from-dotenv.yaml\n")
        monkeypatch.setenv("HARNESS_CONFIG_PATH", "/etc/from-process.yaml")
        assert resolve_config_path(env_file=str(env_file)) == "/etc/from-process.yaml"


# Made with Bob
