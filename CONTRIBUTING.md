# Contributing to simulation-harness

Thanks for your interest in contributing. This document covers the practical
mechanics: setting up an environment, the checks your change has to pass, and how
commits must be signed off.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
For security issues, follow [SECURITY.md](SECURITY.md) rather than opening a
public issue.

## Developer Certificate of Origin (required)

Every commit must carry a `Signed-off-by` trailer certifying that you wrote the
patch, or otherwise have the right to submit it under this project's license. This
is the [Developer Certificate of Origin](https://developercertificate.org/) (DCO).

Add it automatically with `git commit -s`:

```sh
git commit -s -m "feat: add scenario budget override"
```

which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must match your `user.name` and `user.email` git config and be
a real identity — anonymous or pseudonymous sign-offs cannot be accepted.

Forgot to sign off? Fix the whole branch in one step:

```sh
git rebase --signoff main
```

Sign-off is enforced on pull requests by the `DCO` job in
`.github/workflows/ci.yml`, which runs `scripts/check-dco.sh` over the commits
your PR adds. It requires a `Signed-off-by` trailer whose name and email match
the commit's own author, compared case-insensitively. Merge commits and bot
commits (Dependabot) are exempt. You can run it yourself before pushing:

```sh
./scripts/check-dco.sh main HEAD
```

## Getting set up

The project uses [**uv**](https://docs.astral.sh/uv/) for environments and
dependency resolution. Always run Python through `uv run` — a bare `python`,
`python3`, or `pytest` uses the system interpreter and will miss project
dependencies.

```sh
git clone https://github.com/skillberry-ai/simulation-harness.git
cd simulation-harness

make dev-install   # uv sync --extra dev, and installs the git hooks
```

`make dev-install` installs **both** pre-commit hook types (`pre-commit` and
`commit-msg`). Installing only the former silently drops commit-message linting,
so if you set hooks up by hand use `make hooks`. If `core.hooksPath` is set in
your git config, pre-commit refuses to install and `make hooks` will say so.

Copy `.env.example` to `.env` and set `LLM_API_KEY` to run anything that actually
talks to a model. Set `LLM_API_BASE` too if you use a proxy or a non-OpenAI
OpenAI-compatible endpoint. Secrets never belong in `config/harness.yaml`.

## Before you open a pull request

```sh
make check   # ruff lint + mypy type-check + format check
make test    # full unit + integration suite
```

Both must pass. A few more targets that are useful but not part of `make check`:

| Command | Purpose |
|---|---|
| `make test-unit` / `make test-integration` | One suite only |
| `make test-cov` | Coverage, HTML report at `htmlcov/index.html` |
| `make lint-imports` | Enforces the layering contracts in `[tool.importlinter]` |
| `make test-scripts` | Tests for the shell scripts under `scripts/` |
| `make openapi` | Regenerates `openapi.json` — run this if you change the HTTP API |

For a fast inner loop, lint and type-check a single file instead of the whole
tree — each takes well under a second:

```sh
uv run ruff check src/simulation_harness/core/simulation_host.py
uv run ruff format src/simulation_harness/core/simulation_host.py
uv run mypy src/simulation_harness/core/simulation_host.py
```

mypy checks both `src/` and `tests/`. Some `src` modules with pre-existing type
errors are listed under an `ignore_errors` override in `[tool.mypy]`, so the gate
enforces *no new* untyped breakage. If you fully annotate one of those modules,
remove it from that list in the same PR. New test files should be fully
annotated, fixtures included.

`pytest.ini_options` sets `asyncio_mode = "auto"`, so async tests do not need an
`@pytest.mark.asyncio` decorator.

## Commit messages

Commits must follow [Conventional Commits](https://www.conventionalcommits.org/) —
this is enforced by a `commit-msg` hook, not just convention:

```
feat(generation): add scenario budget override
fix(mcp): preserve thread state on failed tool calls
docs: clarify skill reuse semantics
chore(deps): bump dompurify to 3.4.14
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`,
`perf`. Keep the subject in the imperative mood and under ~72 characters.

## What runs in CI

Pull requests are gated on `DCO`, `lint`, `type-check`, `security`, and `test`
jobs (see `.github/workflows/ci.yml`). CodeQL and Dependabot run separately. Pre-commit
locally runs ruff, `detect-secrets`, `bandit`, `shellcheck`, and the
Conventional Commit check, so a clean local commit is usually a green CI run.

If `detect-secrets` flags something, do not regenerate `.secrets.baseline`
wholesale — a full re-scan can silently drop existing entries. Review the diff to
that file before committing it.

## Making a change

Please open an issue before starting anything substantial, so we can agree on the
approach before you invest the effort. Small fixes can go straight to a PR.

For the common change types, follow the shape of the existing example rather than
inventing a new pattern:

| Change | Follow |
|---|---|
| New REST endpoint | `src/simulation_harness/api/v1/simulations.py` |
| New domain error | `src/simulation_harness/utils/errors.py`, then its mapping in `main.py` |
| New agent-callable state tool | `src/simulation_harness/state/tools.py` |
| New skill-generation stage | a stage in `src/simulation_harness/skills/generation/stages/`, wired up in `skills/generator.py` |
| New prompt/skill template | `agent/templates/` or `skills/assets/`, registered in `pyproject.toml` `package-data` |

Conventions that are easy to violate by accident:

- Keep HTTP error mapping centralized in `main.py`. Raise domain errors from route
  handlers; do not catch and translate them there.
- Preserve the stable MCP `reason` codes (`session_expired`,
  `concurrent_queue_full`, `tool_execution_failed`) — clients match on them.
- `SimulationHost` mutates state only inside `_lifecycle_lock`. New lifecycle
  operations must follow that pattern.
- The SSE and streamable-HTTP transports must keep identical `tools/list` and
  `tools/call` semantics.

`CLAUDE.md` documents the architecture in more depth, `THREAT_MODEL.md` covers the
security model, and `docs/` has design notes and deployment guides.

## License

This project is licensed under the [Apache License 2.0](LICENSE). Contributions
are accepted under the same license, as certified by your DCO sign-off.
