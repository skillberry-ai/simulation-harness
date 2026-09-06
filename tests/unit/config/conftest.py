"""Isolation for the config test package.

Every module here exercises code that now consults a `.env` file in the current
working directory (see `config/env_source.py`). Without isolation those tests
would read the *developer's* real `.env` — passing in CI, where no `.env`
exists, and failing locally for anyone who set `HARNESS_LLM_*` in theirs.
Chdir'ing into a `.env`-free tmp dir makes that class of test unwritable:
a test that wants a `.env` has to create one, which documents what it reads.
"""

import pytest


@pytest.fixture(autouse=True)
def _dotenv_free_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Run each config test from a directory with no `.env` in it."""
    monkeypatch.chdir(tmp_path_factory.mktemp("dotenv-free"))


# Made with Bob
