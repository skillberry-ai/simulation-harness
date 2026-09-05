# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python environment

This project uses **uv** for environment and dependency management. Always prefix Python commands with `uv run` — bare `python`, `python3`, or `pytest` will use the system interpreter and miss project dependencies.

- Run tests: `uv run pytest`
- Run a single test: `uv run pytest tests/integration/test_app.py::test_health_check`
- Run a script: `uv run python utils/simulate.py specs/my-api.json`
- Run the server module: `uv run python -m simulation_harness`
- Install dev deps: `make dev-install` (wraps `uv sync --extra dev`)

### Single-file verification (fast inner loop)

Lint and type-check one file without a full build — each runs in well under 5s:

- Lint one file: `uv run ruff check src/simulation_harness/core/simulation_host.py`
- Format one file: `uv run ruff format src/simulation_harness/core/simulation_host.py`
- Type-check one file: `uv run mypy src/simulation_harness/core/simulation_host.py`

mypy (with the `pydantic.mypy` plugin) type-checks **both `src/` and `tests/`**. A few `src` modules with pre-existing type errors are listed under an `ignore_errors` override in `[tool.mypy]` so the gate enforces *no new* untyped breakage — when you fully annotate one, drop it from that override list. New test files should carry full annotations (fixtures included).

## Common commands

| Task | Command |
|---|---|
| Start server | `make start` (PID written to `.harness.pid`) |
| Stop server | `make stop` |
| Restart | `make restart` |
| All tests | `make test` |
| Unit only | `make test-unit` |
| Integration only | `make test-integration` |
| Coverage | `make test-cov` (HTML at `htmlcov/index.html`) |
| Lint | `make lint` (ruff) |
| Format | `make format` |
| Type-check | `make type-check` (mypy) |
| CI check | `make check` (lint + type-check + format-check) |
| Refresh OpenAPI spec | `make openapi` (regenerates `openapi.json`) |
| Cut a release | `make release VERSION=X.Y.Z` (see `docs/releasing.md`) |
| Shell script tests | `make test-scripts` |

`pytest.ini_options` sets `asyncio_mode = "auto"`, so async tests don't need `@pytest.mark.asyncio`.

## Configuration

- Runtime config: `config/harness.yaml` (read once at startup; restart to apply changes). Path is overridable via `HARNESS_CONFIG_PATH`.
- Secrets: `LLM_API_KEY` (and optional `LLM_API_BASE`) come from `.env` or env vars — **not** from the YAML. See `.env.example`.
- Default server port is **8086** (`server.port` in `config/harness.yaml`).

## Architecture (big picture)

The harness is a FastAPI service that, given an OpenAPI spec, spins up an LLM-driven MCP server simulating that API. There is **at most one active simulation per process**.

### Request flow
1. `POST /api/v1/simulation` (in `api/v1/simulations.py`) validates an OpenAPI spec, generates or reuses a skill in the skills folder, and asks `SimulationHost` to create a `SimulationInstance`.
2. `SimulationHost` (`core/simulation_host.py`) is a singleton with a lifecycle lock — it enforces the one-simulation-at-a-time invariant and optionally starts a `SidecarMCPServer` on a separate port (`mcp_port`).
3. `SimulationInstance` (`core/simulation_instance.py`) wraps a `DeepAgent` (LangChain + LangGraph) plus session bookkeeping: tool-call count, idle timer, and a bounded FIFO queue (`asyncio.Lock` + depth counter).
4. MCP requests arrive on either the in-process transport mounted by `main.py` (SSE at `/mcp/sse` + `/mcp/messages`, or streamable HTTP at `/mcp`) or the sidecar server. Both paths construct a `MCPServerWrapper` per request that delegates `tools/call` to the active `SimulationInstance`.
5. The agent loads the generated skill dynamically: `SKILL.md` is exposed via deepagents `SkillsMiddleware` over a `FilesystemBackend` rooted at `skills-store/<name>` (progressive disclosure — the agent reads the skill on demand for the called operation). State is kept in the `schema.json`/`db.json`-backed store via the `state_*` tools. The runtime system prompt carries the state mechanism and JSON contract; per-operation detail lives in the skill.

### Session model invariants
- A single agent thread accumulates context across all `tools/call` invocations for the simulation's lifetime.
- Sessions expire by `max_messages`, idle timeout, or explicit `POST /api/v1/simulation/reset`.
- Concurrent calls serialize through `_queue_lock`; if `_current_queue_depth >= max_queue_depth`, callers get `ConcurrentQueueFullError` (HTTP 503 / MCP `concurrent_queue_full`).
- Failed tool calls preserve thread state; only successful calls increment the counter.

### Skill reuse
`POST /api/v1/simulation` reuses an existing skill if `<skills_folder>/<name>/SKILL.md` exists. Pass `regenerate_skill: true` to force regeneration. The skills folder defaults to `./skills-store` (per `skills.folder` in `harness.yaml`).

### Error handling
Domain exceptions in `utils/errors.py` are mapped to HTTP status by handlers in `main.py`:
- `SimulationAlreadyExistsError`, `PortInUseError` → 409
- `SimulationNotFoundError` → 404
- `OpenAPIValidationError` → 422
- `SessionExpiredError` → 410
- `ConcurrentQueueFullError` → 503

MCP `tools/call` errors return two content blocks: a human-readable text message first, then a JSON block `{"reason": "<code>", ...}` last. Stable reason codes: `session_expired` (+ `limit`, `observed`), `concurrent_queue_full`, `tool_execution_failed`. Preserve these codes when adding new error paths.

### Layout that isn't obvious from the tree
- `agent/templates/` and `skills/assets/` hold Jinja2 prompt templates packaged with the wheel (see `pyproject.toml` `package-data`).
- `state/` is the session-scoped state store the agent uses for cross-call coherence (registry + tools the LLM can invoke).
- `utils/simulate.py` is a CLI for posting a spec to a running harness; `utils/test-client/` is a separate interactive client with its own Makefile.
- `skills-store/` is the configured skills folder for this checkout, and is gitignored — generated skills are build output, not source.

## Conventions worth knowing

- Keep error mapping in `main.py` centralized — don't catch domain errors in route handlers.
- `SimulationHost` mutates state only inside `_lifecycle_lock`; new lifecycle operations should follow the same pattern.
- The MCP transport (SSE vs streamable HTTP) is fixed at startup via `mcp.transport` in YAML; both transports must keep identical `tools/list` / `tools/call` semantics.
- Logs are written per-process to `logs/<timestamp>_pid<PID>_simulation-harness.log`.

## Pattern References

For the common change types, copy the shape of an existing example rather than inventing a new one:

- **New REST endpoint** → follow `src/simulation_harness/api/v1/simulations.py` (request/response Pydantic models in `models/`, raise domain errors, let `main.py` map them to HTTP).
- **New domain error** → add the exception in `src/simulation_harness/utils/errors.py`, then add its HTTP/MCP mapping in `src/simulation_harness/main.py` (keep mapping centralized; preserve the stable MCP `reason` codes).
- **New state tool the agent can call** → see `src/simulation_harness/state/tools.py` (registered via `state/registry.py`, backed by `state/store.py`).
- **New skill-generation stage** → mirror an existing stage in `src/simulation_harness/skills/generation/stages/` (e.g. `operations.py`); wire it into the pipeline in `skills/generator.py`.
- **New prompt/skill template** → add a Jinja2 file under `src/simulation_harness/agent/templates/` or `src/simulation_harness/skills/assets/` and register it in `pyproject.toml` `package-data`.

## DCO Sign-Off (Mandatory)

All commits **must** include a `Signed-off-by` trailer (Developer Certificate of Origin).
Always use the `-s` flag when committing:

```sh
git commit -s -m "feat: Add new feature"
```

This adds a line like `Signed-off-by: Your Name <your@email.com>` to the commit message.
Sign-off is enforced on PRs by the `DCO` job in `.github/workflows/ci.yml`, which runs
`scripts/check-dco.sh`. Merge and bot commits are exempt. To retroactively sign-off
existing commits:

```sh
git rebase --signoff main
```

## Commit Attribution Policy

When creating git commits, do NOT use `Co-Authored-By` trailers for AI attribution.
Instead, use `Assisted-By` to acknowledge AI assistance without inflating contributor stats:

    Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>

Never add `Co-authored-by`, `Made-with`, or similar trailers that GitHub parses as co-authorship.

## Code-quality automation

- **Pre-commit** (`.pre-commit-config.yaml`): ruff lint+format, detect-secrets, shellcheck, and Conventional Commit message enforcement. `make dev-install` installs both hook types; `make hooks` re-installs them on their own. Both are needed — installing only `pre-commit` silently drops commit-message checking. If `core.hooksPath` is set, pre-commit refuses to install and `make hooks` will tell you to clear it.
- **Agent hook** (`.claude/settings.json` → `.claude/hooks/format-python.sh`): auto-formats and autofixes Python files after every Edit/Write.
- **CI** (`.github/workflows/ci.yml`): DCO, lint, type-check, import-boundary, and test gates on every PR. The `DCO` job runs `scripts/check-dco.sh <base> <head>`, which you can also run locally. CodeQL + Dependabot cover security scanning.
- **Import boundaries** (`[tool.importlinter]` in `pyproject.toml`): `make lint-imports` keeps `models`/`utils`/`openapi`/`state` from depending on higher layers.
- **Progressive disclosure**: detailed change patterns live in `.claude/skills/`; path-scoped module rules in `.claude/rules/`. Security analysis is in `THREAT_MODEL.md`.
