# Simulation Harness

A platform-agnostic MCP server simulation harness for testing and developing agent tools and skills without real-world side effects.

## Overview

The Simulation Harness provides a managed environment for simulating MCP (Model Context Protocol) tools and skills. It enables agent developers and DevOps engineers to execute tools without requiring real backends, credentials, or risking irreversible side effects.

**Key Features:**
- 🎯 **Platform-agnostic** — Works with any MCP-capable consumer
- 🔄 **LLM-driven simulation** — Generates plausible, schema-valid responses
- 🚀 **Zero setup** — No credentials, sandboxes, or test data required
- 📦 **Kubernetes-ready** — Standard deployment patterns
- 🔌 **MCP-native** — Exposes tools through standard MCP protocol

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
- **Simulation Instance** — Executes simulated tool calls via LLM
- **Skill Registry** — Manages skill definitions and OpenAPI specs
- **MCP Integration** — Exposes tools through standard MCP protocol

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
```

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
  "openapi_spec": "https://example.com/api/openapi.json",
  "skill_name": "example-skill",
  "session_id": "optional-session-id"
}
```

### List Active Simulations

```bash
GET /api/v1/simulation
```

### Delete a Simulation

```bash
DELETE /api/v1/simulation?session_id=your-session-id
```

### Reset Session State

```bash
POST /api/v1/simulation/reset?session_id=your-session-id
```

## MCP Integration

Once a simulation is created, it exposes MCP tools that can be called by any MCP-compatible client:

```python
# Example: Using the MCP client
from mcp import ClientSession

async with ClientSession(server_url) as session:
    # List available tools
    tools = await session.list_tools()
    
    # Call a tool
    result = await session.call_tool("tool_name", {"arg": "value"})
```

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
│   ├── api/                # FastAPI REST endpoints
│   ├── config/             # Configuration models and settings
│   ├── core/               # Core simulation logic
│   ├── mcp_integration/    # MCP server implementation
│   ├── models/             # Domain models and schemas
│   ├── openapi/            # OpenAPI parsing and validation
│   ├── skills/             # Skill generation and management
│   └── utils/              # Utilities and error handling
├── tests/
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── config/                 # Configuration files
├── docs/                   # Design documentation
└── skills/                 # Skill definitions
```

## Deployment

### Docker

```bash
# Build image
docker build -t simulation-harness:latest .

# Run container
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your-key \
  -v $(pwd)/config:/app/config \
  simulation-harness:latest
```

### Kubernetes

```bash
# Apply manifests
kubectl apply -f k8s/

# Check status
kubectl get pods -l app=simulation-harness
```

See `docs/design/DESIGN.md` for detailed deployment configurations.

## Documentation

Comprehensive design documentation is available in the `docs/design/` directory:

- **[README.md](docs/design/README.md)** — Master document and index
- **[USER_NEED.md](docs/design/USER_NEED.md)** — User personas and use cases
- **[REQUIREMENTS.md](docs/design/REQUIREMENTS.md)** — Technical requirements
- **[DESIGN.md](docs/design/DESIGN.md)** — Architecture and component design
- **[ALPHA_USE_CASE.md](docs/design/ALPHA_USE_CASE.md)** — Skillberry Store integration example

## Roadmap

### Phase 1 (Current) — Foundation
- ✅ Single OpenAPI spec → single skill → single simulation
- ✅ MCP tool exposure
- ✅ Session management
- ✅ Basic error handling

### Phase 2 — Multi-Service Composition
- Multiple OpenAPI specs per simulation
- Cross-service state management

### Phase 3 — Runtime Skill Mutation
- Dynamic skill updates
- Conversational skill refinement

### Phase 4 — Production Readiness
- Authentication and multi-tenancy
- Persistent storage
- Advanced observability

## Contributing

Contributions are welcome! Please ensure:
- All tests pass (`pytest`)
- Code follows project conventions
- New features include tests and documentation

## License

[License information to be added]

## Support

For questions, issues, or feature requests, please [open an issue](link-to-issues).

---

**Status:** Phase 1 — Foundation (Draft)  
**Last Updated:** 2026-05-30