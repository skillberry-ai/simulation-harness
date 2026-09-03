# Simulation Harness

A platform-agnostic MCP server simulation harness for testing and developing agent tools and skills without real-world side effects.

## Overview

The Simulation Harness provides a managed environment for simulating MCP (Model Context Protocol) tools and skills. It enables agent developers and DevOps engineers to execute tools without requiring real backends, credentials, or risking irreversible side effects.

**Key Features:**
- Platform-agnostic — works with any MCP-capable consumer
- LLM-driven simulation — generates plausible, schema-valid responses
- Zero setup — no credentials, sandboxes, or test data required
- Service-level simulation — one OpenAPI spec → one skill → one simulation
- MCP-native — exposes tools through standard MCP protocol (SSE & Streamable HTTP)
- Stateful sessions — multi-call coherence with configurable limits
- Robust error handling — structured error payloads with detailed diagnostics

## Use Cases

### 1. Catalog Exploration ("Try")
Quickly evaluate tools before integration. Click "Try" in a catalog UI and see realistic mock responses in seconds.

### 2. Skill/Tool Optimization
Run hundreds of optimization trials per hour without consuming real API budgets or producing side effects.

### 3. Runtime Course-of-Action Rehearsal
Let agents rehearse actions with potentially irreversible impacts before executing them for real.

## Architecture

The harness consists of:
- **Simulation Host** — manages the singleton simulation lifecycle and routing
- **Simulation Instance** — executes simulated tool calls via LLM (LangChain + LangGraph)
- **Skill Registry** — manages skill definitions and OpenAPI specs, gating reuse vs. regeneration
- **Skill Generation Pipeline** — turns an OpenAPI spec into a simulation skill via staged LLM calls (see [docs/simulation-generation.md](docs/simulation-generation.md))
- **MCP Integration** — exposes tools through standard MCP protocol (SSE & Streamable HTTP transports)
- **State Management** — per-session state store the agent uses for cross-call coherence

### Session Model

Each harness process hosts **at most one active simulation** with a single stateful agent thread:
- All MCP `tools/call` invocations land on this thread for context accumulation
- Sessions expire on tool-call count (`max_messages`), idle timeout, or explicit reset
- Concurrent calls are serialized via a bounded FIFO queue (configurable depth); excess calls are rejected with `concurrent_queue_full`
- Failed calls preserve thread state; only successful calls advance counters

## Quick Start

### Prerequisites
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) for environment and dependency management
- An LLM provider API key (OpenAI, Azure OpenAI, or any LiteLLM-compatible provider)

### Installation

```bash
git clone <repository-url>
cd simulation-harness

# Install dev dependencies (wraps `uv sync` + ruff)
make dev-install
```

### Configuration

Runtime settings live in `config/harness.yaml`. The shipped defaults:

```yaml
llm:
  provider: openai
  skill_generation_model: gpt-4.1
  simulation_model: gpt-4.1
  temperature: 0

skills:
  folder: ./skills-store

sessions:
  max_messages: 100
  idle_timeout_seconds: 3600
  max_concurrent_queue_depth: 8

mcp:
  transport: sse  # or streamable_http

server:
  host: 0.0.0.0
  port: 8086

logging:
  level: INFO
  destination_folder: ./logs
```

**Configuration notes:**
- The YAML is read once at startup; changes require a process restart. Override the path via `HARNESS_CONFIG_PATH`.
- Individual values can be overridden with `HARNESS_*` env vars — including the models, via `HARNESS_LLM_SKILL_GENERATION_MODEL` and `HARNESS_LLM_SIMULATION_MODEL`. See the [full table](deploy/README.md#env-var-config-overrides), useful when the YAML isn't yours to edit.
- Secrets are **not** in the YAML. Set `LLM_API_KEY` (and optional `LLM_API_BASE`) via `.env` or environment variables — see [`.env.example`](.env.example).
- The MCP transport (`sse` vs `streamable_http`) is fixed at startup — both expose identical `tools/list` and `tools/call` semantics.

### Running the service

```bash
# Provide your LLM credentials
export LLM_API_KEY=your-api-key-here
# export LLM_API_BASE=https://your-resource.openai.azure.com/  # optional

# Start / stop / restart (PID stored in .harness.pid)
make start
make stop
make restart
```

The service listens on `http://localhost:8086` by default.

### Make targets

```bash
make help              # Show all available targets
make install           # Install production dependencies
make dev-install       # Install development dependencies
make start             # Start the harness server
make stop              # Stop the harness server
make restart           # Restart the harness server
make test              # Run all tests
make test-unit         # Run unit tests only
make test-integration  # Run integration tests only
make test-cov          # Run tests with coverage report (HTML at htmlcov/index.html)
make lint              # Run ruff linter
make format            # Format code with ruff
make check             # Run lint and format check (CI mode)
make clean             # Remove generated files and caches
```

## API

The full integrator's reference — REST endpoints, MCP transport details, error
codes, and a worked end-to-end example — lives in **[docs/api.md](docs/api.md)**.

A live, schema-typed view is also available on the running service at `/docs`
(Swagger UI), `/redoc`, and `/openapi.json`.

A short tour:

```bash
BASE=http://localhost:8086

# 1. Start creation — returns 202 Accepted with status "pending"
curl -sS -X POST "$BASE/api/v1/simulation" \
  -H 'content-type: application/json' \
  -d @path/to/openapi.json

# 2. Poll until status becomes "ready" (or "failed")
#    Typical wait: a few seconds for skill reuse, ~10–60s for first-time generation
curl -sS "$BASE/api/v1/simulation"

# 3. Once ready: list the MCP tools the simulation exposes (no MCP client required)
curl -sS "$BASE/api/v1/simulation/tools"

# Reset session counters without tearing the simulation down
curl -sS -X POST "$BASE/api/v1/simulation/reset"

# Tear it down
curl -sS -X DELETE "$BASE/api/v1/simulation"
```

### Two-phase flow: setup then start

`POST /api/v1/simulation` is the convenience path (generate artifacts **and**
open a session in one call). For build/deploy pipelines you can split the two
phases so artifact generation happens once, offline, and each boot merely opens
a session from the baked artifacts:

```bash
# Build time (offline, no server) — generate the four artifacts
# (SKILL.md, schema.json, db.json, api.json) into the skills folder.
uv run python -m simulation_harness.setup_cli path/to/openapi.json \
  [--name my-api] [--regenerate]

# …or against a running server: generate artifacts, no session.
# Returns 202; poll GET /simulation until status becomes "generated".
curl -sS -X POST "$BASE/api/v1/simulation/setup" \
  -H 'content-type: application/json' -d @path/to/openapi.json

# Start a session from baked artifacts — no OpenAPI spec required.
# The spec is reconstructed from the baked api.json. 404 if artifacts are missing.
curl -sS -X POST "$BASE/api/v1/simulation/start" \
  -H 'content-type: application/json' -d '{"name": "my-api"}'
```

**Auto-start on boot.** Autostart is **opt-in** and off by default. Set
`startup.autostart_enabled: true` in `config/harness.yaml` (or
`HARNESS_AUTOSTART_ENABLED=true`) to open a session from baked artifacts when the
server starts; with it `false` (the default) the harness always boots idle and
ignores any baked skills. When enabled, `startup.autostart_simulation` (or the
`HARNESS_AUTOSTART_SIMULATION` env var) picks which skill starts. Resolution
precedence when no name is given: **0** baked skills → boot idle; **1** → start
it; **more than one** → start the most recently generated one and log a warning.
An explicitly-named skill with no complete artifacts fails readiness (`/readyz`
returns 503).

Once a simulation is ready, MCP clients connect according to the configured
transport:

- **SSE** — `GET /mcp/sse` paired with `POST /mcp/messages` (default).
- **Streamable HTTP** — `POST /mcp` (single endpoint).
- **Sidecar port** — pass `mcp_port` on create to run the MCP server on a
  dedicated port; the create response's `mcp_url` reflects the chosen address.

Health and Kubernetes probe endpoints: `/health`, `/healthz`, `/readyz`.

See [docs/api.md](docs/api.md) for request/response shapes, error mapping, and
session lifecycle details.

## Docker / Kubernetes

Build and run the harness as a container, or deploy it to a Kubernetes cluster.

```bash
# Local Docker
docker build -t simulation-harness:dev .
docker run --rm -p 8086:8086 -e LLM_API_KEY="$LLM_API_KEY" simulation-harness:dev

# docker compose
LLM_API_KEY=... docker compose up -d

# Kubernetes (kustomize)
kubectl apply -k deploy/k8s/
```

See [`deploy/README.md`](deploy/README.md) for the full env-var reference,
probe semantics, and rollout commands.

### Published image tags

Images are published to `ghcr.io/skillberry-ai/simulation-harness`:

| Tag | Points at | Moves when |
|---|---|---|
| `latest` | newest release | a `vX.Y.Z` tag is pushed |
| `X.Y.Z` (e.g. `0.1.2`) | one exact release | never |
| `X.Y` (e.g. `0.1`) | newest patch on that minor line | a `vX.Y.*` release is cut |
| `main` | newest `main` build | every push to `main` |
| `sha-<short-sha>` | one commit | never |

`latest` follows **releases, not `main`** — it is what a bare `docker pull`
resolves to, so it points at released code. Use `main` to track trunk.

Pre-release tags (`v0.3.0-rc1`) publish only their exact version; they never move
`latest` or a `X.Y` line. For production, pin `X.Y.Z` or a digest — the build
summary prints the digest for each image.

**Deployment notes:**
- Each instance hosts exactly one simulation (one OpenAPI spec → one skill → one MCP endpoint).
- Multi-service orchestration is handled at the deployment layer (multiple instances).
- The MCP URL is the simulation identifier.
- Phase 1 is single-tenant per instance; deploy more instances for concurrent users.

## Simulate CLI

`utils/simulate.py` posts an OpenAPI JSON file to a running harness:

```bash
uv run python utils/simulate.py path/to/openapi.json
```

| Argument | Description |
|---|---|
| `openapi_file` | Path to the OpenAPI JSON spec file (required). |
| `--name NAME` | Override the simulation name (default: uses `info.title`). |
| `--regenerate-skill` | Force skill regeneration even if one already exists. |
| `--config PATH` | Path to `harness.yaml` (default: `config/harness.yaml`). |

The utility reads the server host and port from `harness.yaml` and POSTs the
spec to `POST /api/v1/simulation`. The endpoint returns `202 Accepted`
immediately; the utility then polls `GET /api/v1/simulation` until the status
reaches `ready` (or `failed`) and prints the final response JSON. On failure it
exits non-zero and writes the error to stderr.

## Get-bundle CLI

`utils/get_bundle.py` exports the full generated skill bundle for the active
simulation via `GET /api/v1/simulation/bundle` and prints the JSON envelope
(name + verbatim files + per-file uncompressed sizes) to stdout:

```bash
uv run python utils/get_bundle.py
```

| Argument | Description |
|---|---|
| `--gzip` | Request a gzip-compressed response and report the compression ratio on stderr. |
| `--output-dir PATH` | Reconstruct the bundle's verbatim files under `PATH/<name>/`. |
| `--config PATH` | Path to `harness.yaml` (default: `config/harness.yaml`). |

Diagnostics (compression ratio, files-written notice) go to stderr, so stdout
stays clean JSON for piping. `--output-dir` writes each file byte-for-byte, so a
restored `skills-store/<name>/` opens with no regeneration. On failure it exits
non-zero and writes the error to stderr.

## Test client

An interactive PatternFly + React test client lives in [`utils/test-client/`](utils/test-client/) with its own Makefile:

```bash
cd utils/test-client
make setup
make dev      # client on :5173, proxy on :3000
```

Features:
- Create simulations from OpenAPI specs (Monaco editor + example loader)
- List and call MCP tools (schema-driven forms)
- Inspect session state, schema, and database
- Browse and export request history

See [`utils/test-client/README.md`](utils/test-client/README.md) for production run and configuration.

## Development

### Running tests

```bash
make test           # all tests
make test-unit      # unit tests
make test-integration
make test-cov       # with coverage (HTML at htmlcov/index.html)
```

`pytest.ini_options` sets `asyncio_mode = "auto"`, so async tests don't need `@pytest.mark.asyncio`.

### Code quality

```bash
make lint           # ruff
make format         # ruff format
make check          # lint + format check (CI mode)
```

### Project structure

```
simulation-harness/
├── src/simulation_harness/
│   ├── agent/              # LLM agent and prompt management
│   │   ├── deep_agent.py   # LangChain + LangGraph agent
│   │   ├── prompts.py
│   │   ├── session_manager.py
│   │   ├── skill_backend.py        # Filesystem backend for skill loading
│   │   └── templates/      # Jinja2 prompt templates (packaged)
│   ├── api/v1/             # FastAPI REST endpoints
│   ├── config/             # Configuration models
│   ├── core/               # Core simulation logic
│   │   ├── simulation_host.py      # Singleton lifecycle
│   │   ├── simulation_instance.py  # Per-call execution
│   │   ├── simulation_creator.py   # Async create pipeline
│   │   ├── simulation_record.py    # Create/status bookkeeping
│   │   └── skill_registry.py       # Reuse-vs-generate gate
│   ├── mcp_integration/    # MCP server (SSE + Streamable HTTP, sidecar)
│   ├── models/             # Domain models and schemas
│   ├── openapi/            # Spec parsing, validation, tool generation
│   ├── skills/             # Skill generation (see docs/simulation-generation.md)
│   │   ├── generator.py    # Atomic skill-bundle writer
│   │   ├── generation/     # Multi-stage generation pipeline
│   │   │   ├── pipeline.py # Stage orchestrator
│   │   │   ├── ir.py       # SpecModel intermediate representation
│   │   │   ├── repair.py   # Produce → validate → re-prompt loop
│   │   │   └── stages/     # analyze, operations, schema, scenarios, seed, assemble
│   │   └── assets/         # Jinja2 + prompt templates (packaged)
│   ├── state/              # Per-session state store + tools
│   ├── utils/              # Errors and helpers
│   ├── main.py             # FastAPI app + error handlers
│   └── __main__.py         # `python -m simulation_harness`
├── tests/
│   ├── unit/               # Mirrors src structure
│   └── integration/        # Full-app, MCP, session limits, lifecycle
├── config/harness.yaml     # Runtime configuration
├── deploy/                 # Docker & Kubernetes manifests
│   └── k8s/                # Kustomize base
├── docs/
│   ├── api.md                      # API reference
│   ├── simulation-generation.md    # Skill-generation pipeline guide
│   └── design/                     # Design documents
├── skills-store/           # Generated skills (configured skills folder)
├── utils/
│   ├── simulate.py         # CLI for creating simulations
│   ├── get_bundle.py       # CLI for exporting the full skill bundle
│   └── test-client/        # Interactive test client
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

## Documentation

- **[API reference](docs/api.md)** — REST + MCP integrator's guide
- **[Simulation generation](docs/simulation-generation.md)** — how an OpenAPI spec becomes a simulation skill (the generation pipeline, stage by stage)
- **[Deployment guide](deploy/README.md)** — Docker and Kubernetes
- **Design documents** in `docs/design/`:
  - [README.md](docs/design/README.md) — master document and index
  - [USER_NEED.md](docs/design/USER_NEED.md) — user personas and use cases
  - [REQUIREMENTS.md](docs/design/REQUIREMENTS.md) — technical requirements
  - [DESIGN.md](docs/design/DESIGN.md) — architecture and component design
  - [ALPHA_USE_CASE.md](docs/design/ALPHA_USE_CASE.md) — Skillberry Store integration

## Roadmap

### Phase 1 — Foundation (current)
- Single OpenAPI spec → single skill → single simulation
- MCP tool exposure (SSE & Streamable HTTP)
- Session management with configurable limits and bounded FIFO queue
- Skill generation and reuse (atomic temp-dir pattern)
- Stateful agent thread with multi-call coherence
- Structured error handling with detailed diagnostics
- OpenAPI 3.0.x and 3.1.x validation
- Per-tool-call logging with outcome tracking
- Docker image and Kubernetes manifests

### Phase 2 — Multi-Service Composition
- Multiple OpenAPI specs per simulation
- Cross-service state management
- Dual-transport concurrent operation

### Phase 3 — Runtime Skill Mutation
- Dynamic skill updates
- Conversational skill refinement
- Spec fingerprinting for reuse validation

### Phase 4 — Production Readiness
- Authentication and multi-tenancy
- Persistent storage (beyond in-memory checkpointer)
- Advanced observability (Prometheus, OpenTelemetry)
- Application-level rate limiting and cost caps
- Configuration hot-reload

## Contributing

Contributions are welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)** for the
full guide. In short:

- Every commit needs a DCO sign-off (`git commit -s`) and a
  [Conventional Commits](https://www.conventionalcommits.org/) subject.
- `make check` (lint + type-check + format) and `make test` must pass.
- New features include tests and documentation.
- Changes align with the design documents in `docs/design/`.

By participating you agree to our [Code of Conduct](CODE_OF_CONDUCT.md). To report
a security vulnerability, follow [SECURITY.md](SECURITY.md) — please don't open a
public issue.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for
attribution.

Copyright IBM Corp. 2026
