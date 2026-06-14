# Simulation Harness

A platform-agnostic MCP server simulation harness for testing and developing agent tools and skills without real-world side effects.

## Overview

The Simulation Harness provides a managed environment for simulating MCP (Model Context Protocol) tools and skills. It enables agent developers and DevOps engineers to execute tools without requiring real backends, credentials, or risking irreversible side effects.

**Key Features:**
- 🎯 **Platform-agnostic** — Works with any MCP-capable consumer
- 🔄 **LLM-driven simulation** — Generates plausible, schema-valid responses
- 🚀 **Zero setup** — No credentials, sandboxes, or test data required
- 📦 **Service-level simulation** — One OpenAPI spec → one skill → one simulation
- 🔌 **MCP-native** — Exposes tools through standard MCP protocol (SSE & Streamable HTTP)
- 🧵 **Stateful sessions** — Multi-call coherence with configurable limits
- 🛡️ **Robust error handling** — Structured error payloads with detailed diagnostics

## Use Cases

### 1. Catalog Exploration ("Try")
Quickly evaluate tools before integration. Click "Try" in a catalog UI and see realistic mock responses in seconds.

### 2. Skill/Tool Optimization
Run hundreds of optimization trials per hour without consuming real API budgets or producing side effects.

### 3. Runtime Course-of-Action Rehearsal
Let agents rehearse actions with potentially irreversible impacts before executing them for real.

## Architecture

The harness consists of:
- **Simulation Host** — Manages simulation lifecycle and routing
- **Simulation Instance** — Executes simulated tool calls via LLM (LangChain + LangGraph)
- **Skill Registry** — Manages skill definitions and OpenAPI specs
- **MCP Integration** — Exposes tools through standard MCP protocol (SSE & Streamable HTTP transports)
- **State Management** — Persistent session state with configurable expiry

### Session Model

Each harness instance hosts **one stateful agent thread** for the lifetime of the simulation:
- All MCP `tools/call` invocations land on this single thread for context accumulation
- Sessions expire based on: tool-call count (`max_messages`), idle timeout, or explicit reset
- Concurrent calls are serialized via a bounded FIFO queue (configurable depth)
- Failed calls preserve thread state; successful calls advance counters

## Quick Start

### Prerequisites
- Python 3.11+
- OpenAI API key (or compatible LLM provider)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd simulation-harness

# Install dependencies
make dev-install

# Or manually with uv
uv sync
```

### Configuration

Create a configuration file at `config/harness.yaml`:

```yaml
llm:
  provider: openai
  api_key_env: OPENAI_API_KEY
  skill_generation_model: gpt-4
  simulation_model: gpt-4
  temperature: 0

skills:
  folder: ./skills

sessions:
  max_messages: 100
  idle_timeout_seconds: 3600
  max_concurrent_queue_depth: 8

mcp:
  transport: sse  # or streamable_http

server:
  host: 0.0.0.0
  port: 8000

logging:
  level: INFO
  destination_folder: ./logs
```

**Configuration Notes:**
- The YAML is read once at startup; changes require a process restart
- API keys can be literal values or environment variable references
- `api_base_env` supports custom endpoints for self-hosted/gateway deployments
- MCP transport selection is configured (not runtime) — choose `sse` or `streamable_http`

### Running the Service

```bash
# Set your API key
export OPENAI_API_KEY=your-key-here

# Start the harness
make start

# Stop the harness
make stop

# Restart the harness
make restart
```

The service will start on `http://localhost:8000` by default.

### Available Make Targets

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
make test-cov          # Run tests with coverage report
make lint              # Run ruff linter
make format            # Format code with ruff
make check             # Run lint and format check (CI mode)
make clean             # Remove generated files and caches
```

## API Usage

### Create a Simulation

```bash
POST /api/v1/simulation
Content-Type: application/json

{
  "openapi_spec": { ... },  # Inline OpenAPI 3.0.x or 3.1.x JSON
  "skill_name": "example-skill",
  "session_id": "optional-session-id",
  "regenerate": false  # Optional: force skill regeneration
}
```

**Skill Reuse:** The harness automatically reuses existing skills if `<skills_folder>/<name>/SKILL.md` exists. Pass `regenerate: true` to force regeneration. A warning is logged on reuse to remind operators to regenerate if the spec changed.

**Validation:** OpenAPI specs are validated via `openapi-spec-validator`. Both 3.0.x and 3.1.x are supported. Request body is capped at 10 MB. Validation failures return 422 with structured errors.

### List Active Simulations

```bash
GET /api/v1/simulation
```

Returns simulation details including live session counters:
- `tool_call_count` — Number of successful tool calls
- `max_messages` — Configured limit
- `seconds_since_last_call` — Idle time
- `idle_timeout_seconds` — Configured timeout
- `queue_depth` — Current queue size
- `max_concurrent_queue_depth` — Configured queue limit

### Delete a Simulation

```bash
DELETE /api/v1/simulation?session_id=your-session-id
```

### Reset Session State

```bash
POST /api/v1/simulation/reset?session_id=your-session-id
```

Clears the singleton thread; the next tool call starts fresh.

## MCP Integration

Once a simulation is created, it exposes MCP tools through the configured transport:

### SSE Transport
- Endpoint: `GET /mcp/sse` (with companion `POST /mcp/messages`)
- Standard Server-Sent Events transport

### Streamable HTTP Transport
- Endpoint: `/mcp` (single ASGI mount)
- Stateless mode (no `Mcp-Session-Id` negotiation)

### Transport Parity
Both transports provide identical functionality:
- Same `tools/list` and `tools/call` semantics
- Same structured error payloads
- Same session bookkeeping behavior

### Example Usage

```python
from mcp import ClientSession

async with ClientSession(server_url) as session:
    # List available tools
    tools = await session.list_tools()
    
    # Call a tool
    result = await session.call_tool("tool_name", {"arg": "value"})
```

### Error Handling

MCP `tools/call` returns structured errors with `isError: true` and detailed `reason` fields:

- `max_messages_exceeded` — Session hit tool-call limit
- `idle_timeout_exceeded` — Session idle timeout expired
- `concurrent_queue_full` — Queue depth exceeded
- `llm_provider_error` — LLM provider failure
- `tool_invocation_error` — Tool execution failure
- `internal_error` — Harness internal error

Error payloads include relevant context (limits, observed values) for programmatic handling.

## Development

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test suites
make test-unit
make test-integration
```

### Code Quality

```bash
# Run linter
make lint

# Format code
make format

# Check formatting and linting (CI mode)
make check
```

### Project Structure

```
simulation-harness/
├── src/simulation_harness/
│   ├── agent/              # LLM agent and prompt management
│   │   ├── deep_agent.py   # LangChain + LangGraph agent
│   │   ├── prompts.py      # Prompt templates
│   │   ├── session_manager.py  # Session lifecycle
│   │   └── templates/      # Jinja2 templates
│   ├── api/                # FastAPI REST endpoints
│   │   └── v1/             # API v1 routes
│   ├── config/             # Configuration models and settings
│   ├── core/               # Core simulation logic
│   │   ├── simulation_host.py      # Simulation lifecycle
│   │   ├── simulation_instance.py  # Tool execution
│   │   └── skill_registry.py       # Skill management
│   ├── mcp_integration/    # MCP server implementation
│   │   ├── mcp_server.py   # MCP server wrapper
│   │   └── transport.py    # SSE & Streamable HTTP
│   ├── models/             # Domain models and schemas
│   ├── openapi/            # OpenAPI parsing and validation
│   │   ├── parser.py       # OpenAPI spec parsing
│   │   ├── schema_validator.py  # Schema validation
│   │   └── tool_generator.py    # MCP tool generation
│   ├── skills/             # Skill generation and management
│   │   ├── generator.py    # Skill generation utility
│   │   └── assets/         # Prompt templates
│   ├── state/              # State management
│   │   ├── store.py        # State storage
│   │   ├── registry.py     # State registry
│   │   ├── tools.py        # State manipulation tools
│   │   └── validator.py    # State validation
│   └── utils/              # Utilities and error handling
├── tests/
│   ├── unit/               # Unit tests (mirrors src structure)
│   └── integration/        # Integration tests
│       ├── test_app.py     # Full app lifecycle
│       ├── test_mcp_tools.py  # MCP tool execution
│       ├── test_session_limits.py  # Session expiry
│       └── test_simulation_lifecycle.py
├── config/                 # Configuration files
│   └── harness.yaml        # Main configuration
├── docs/                   # Design documentation
│   └── design/
│       ├── README.md       # Master document
│       ├── USER_NEED.md    # User personas
│       ├── REQUIREMENTS.md # Technical requirements
│       ├── DESIGN.md       # Architecture details
│       └── ALPHA_USE_CASE.md  # Skillberry integration
├── utils/                  # Development utilities
│   ├── simulate.py         # CLI for creating simulations
│   └── test-client/        # Interactive test client
└── skills/                 # Generated skill definitions
```

## Docker / Kubernetes

Build and run the harness as a container, or deploy it to a Kubernetes cluster.

```bash
# Local
docker build -t simulation-harness:dev .
docker run --rm -p 8086:8086 -e LLM_API_KEY="$LLM_API_KEY" simulation-harness:dev

# docker compose
LLM_API_KEY=... docker compose up -d

# Kubernetes
kubectl apply -k deploy/k8s/
```

See [`deploy/README.md`](deploy/README.md) for the full env-var reference,
probe semantics, and rollout commands.

**Deployment Notes:**
- Each instance hosts exactly one simulation (one OpenAPI spec → one skill → one MCP endpoint)
- Multi-service orchestration is handled at the deployment layer (multiple instances)
- The MCP URL is the simulation identifier
- Phase 1 is single-tenant per instance; deploy more instances for concurrent users

## Simulate CLI

`utils/simulate.py` is a command-line utility for creating simulations directly from an OpenAPI JSON file:

```bash
python utils/simulate.py path/to/openapi.json
```

**Arguments:**

| Argument | Description |
|---|---|
| `openapi_file` | Path to the OpenAPI JSON spec file (required) |
| `--name NAME` | Override the simulation name (default: uses `info.title` from the spec) |
| `--regenerate-skill` | Force skill regeneration even if one already exists |
| `--config PATH` | Path to `harness.yaml` (default: `config/harness.yaml`) |

**Examples:**

```bash
# Create a simulation from a spec
python utils/simulate.py specs/my-api.json

# Override the simulation name
python utils/simulate.py specs/my-api.json --name staging-api

# Force skill regeneration
python utils/simulate.py specs/my-api.json --regenerate-skill

# Use a custom config path
python utils/simulate.py specs/my-api.json --config /path/to/harness.yaml
```

The utility reads the server host and port from `harness.yaml` and POSTs the spec to `POST /api/v1/simulation`. On success it prints the response JSON; on failure it exits with a non-zero status and writes the error to stderr.

## Test Client

An interactive test client is available in `utils/test-client/`:

```bash
cd utils/test-client
make setup
make run
```

Features:
- Create simulations from OpenAPI specs
- List and call MCP tools
- Monitor session state
- Test both SSE and Streamable HTTP transports

## Documentation

Comprehensive design documentation is available in the `docs/design/` directory:

- **[README.md](docs/design/README.md)** — Master document and index
- **[USER_NEED.md](docs/design/USER_NEED.md)** — User personas and use cases
- **[REQUIREMENTS.md](docs/design/REQUIREMENTS.md)** — Technical requirements
- **[DESIGN.md](docs/design/DESIGN.md)** — Architecture and component design
- **[ALPHA_USE_CASE.md](docs/design/ALPHA_USE_CASE.md)** — Skillberry Store integration example

## Current Status

### Phase 1 — Foundation (Complete)

**Implemented Features:**
- ✅ Single OpenAPI spec → single skill → single simulation
- ✅ MCP tool exposure (SSE & Streamable HTTP transports)
- ✅ Session management with configurable limits
- ✅ Skill generation and reuse
- ✅ Stateful agent thread with multi-call coherence
- ✅ Bounded FIFO queue for concurrent calls
- ✅ Structured error handling with detailed diagnostics
- ✅ OpenAPI 3.0.x and 3.1.x validation
- ✅ Comprehensive test coverage (unit + integration)
- ✅ Interactive test client
- ✅ Per-tool-call logging with outcome tracking

**Architecture Highlights:**
- LangChain + LangGraph based Deep Agent
- FastAPI REST management API
- MCP protocol integration via official SDK
- YAML-based configuration
- Atomic skill generation with temp-dir pattern
- Session expiry with fail-then-reset semantics

## Roadmap

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

Contributions are welcome! Please ensure:
- All tests pass (`make test`)
- Code follows project conventions (`make check`)
- New features include tests and documentation
- Changes align with design documents in `docs/design/`

## License

[License information to be added]

## Support

For questions, issues, or feature requests, please [open an issue](link-to-issues).

---

**Status:** Phase 1 — Foundation (Complete)  
**Last Updated:** 2026-06-01  
**Python:** 3.11+  
**MCP SDK:** 1.0.0+