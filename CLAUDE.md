# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Python environment

This project uses **uv** for environment and dependency management. Always prefix Python commands with `uv run` — bare `python`, `python3`, or `pytest` will use the system interpreter and miss project dependencies.

- Run tests: `uv run pytest`
- Run a single test: `uv run pytest tests/integration/test_app.py::test_health_check`
- Run a script: `uv run python utils/simulate.py specs/my-api.json`
- Run the server module: `uv run python -m simulation_harness`
- Install dev deps: `make dev-install` (wraps `uv sync` + ruff)

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
| CI check | `make check` (lint + format-check) |

`pytest.ini_options` sets `asyncio_mode = "auto"`, so async tests don't need `@pytest.mark.asyncio`.

## Configuration

- Runtime config: `config/harness.yaml` (read once at startup; restart to apply changes). Path is overridable via `HARNESS_CONFIG_PATH`.
- Secrets: `LLM_API_KEY` (and optional `LLM_API_BASE`) come from `.env` or env vars — **not** from the YAML. See `.env.example`.
- Default server port is **8086** in `config/harness.yaml` (not 8000 as the README suggests).

## Architecture (big picture)

The harness is a FastAPI service that, given an OpenAPI spec, spins up an LLM-driven MCP server simulating that API. There is **at most one active simulation per process**.

### Request flow
1. `POST /api/v1/simulation` (in `api/v1/simulations.py`) validates an OpenAPI spec, generates or reuses a skill in the skills folder, and asks `SimulationHost` to create a `SimulationInstance`.
2. `SimulationHost` (`core/simulation_host.py`) is a singleton with a lifecycle lock — it enforces the one-simulation-at-a-time invariant and optionally starts a `SidecarMCPServer` on a separate port (`mcp_port`).
3. `SimulationInstance` (`core/simulation_instance.py`) wraps a `DeepAgent` (LangChain + LangGraph) plus session bookkeeping: tool-call count, idle timer, and a bounded FIFO queue (`asyncio.Lock` + depth counter).
4. MCP requests arrive on either the in-process transport mounted by `main.py` (SSE at `/mcp/sse` + `/mcp/messages`, or streamable HTTP at `/mcp`) or the sidecar server. Both paths construct a `MCPServerWrapper` per request that delegates `tools/call` to the active `SimulationInstance`.
5. The agent uses the generated skill (in `skills-store/<name>/SKILL.md`) plus operation schemas to synthesize a plausible response, advancing session state on success.

### Session model invariants
- A single agent thread accumulates context across all `tools/call` invocations for the simulation's lifetime.
- Sessions expire by `max_messages`, idle timeout, or explicit `POST /api/v1/simulation/reset`.
- Concurrent calls serialize through `_queue_lock`; if `_current_queue_depth >= max_queue_depth`, callers get `ConcurrentQueueFullError` (HTTP 503 / MCP `concurrent_queue_full`).
- Failed tool calls preserve thread state; only successful calls increment the counter.

### Skill reuse
`POST /api/v1/simulation` reuses an existing skill if `<skills_folder>/<name>/SKILL.md` exists. Pass `regenerate: true` to force regeneration. The skills folder defaults to `./skills-store` (per `harness.yaml`), not `./skills` as the README example shows.

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
- `skills-store/` is the configured skills folder for this checkout (the README shows `./skills/` as a placeholder).

## Conventions worth knowing

- Keep error mapping in `main.py` centralized — don't catch domain errors in route handlers.
- `SimulationHost` mutates state only inside `_lifecycle_lock`; new lifecycle operations should follow the same pattern.
- The MCP transport (SSE vs streamable HTTP) is fixed at startup via `mcp.transport` in YAML; both transports must keep identical `tools/list` / `tools/call` semantics.
- Logs are written per-process to `logs/<timestamp>_pid<PID>_simulation-harness.log`.
