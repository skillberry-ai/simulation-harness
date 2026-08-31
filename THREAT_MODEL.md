# Threat Model: simulation-harness

## 1. System context

simulation-harness is a FastAPI service that, given an OpenAPI specification, spins
up an LLM-driven MCP server that *simulates* the described API without hitting any
real backend. A caller `POST`s an OpenAPI spec; the harness validates it, generates
(or reuses) a "skill" describing each operation, and starts an MCP server. MCP
clients then call tools (one per OpenAPI operation) whose responses are synthesised
by an LLM using the spec's schemas and examples, with cross-call state kept in a
session-scoped JSON store.

Security assumptions:

- The service runs in a trusted environment (developer machine, CI, or an internal
  cluster) and is **not** intended to be exposed directly to the public internet.
- Callers who can submit a spec are semi-trusted (developers/testers), but their
  **input specs are untrusted data**.
- The configured LLM endpoint (`LLM_API_BASE`/`LLM_API_KEY`) is trusted to receive
  spec-derived content.
- At most one simulation is active per process (enforced by `SimulationHost`).

## 2. Assets

| asset | description | sensitivity |
|---|---|---|
| `LLM_API_KEY` | Credential for the upstream LLM provider | high |
| Submitted OpenAPI specs | May embed proprietary API designs | medium |
| Generated skills (`skills-store/`) | Derived artefacts written to disk | low |
| Session state store (`schema.json`/`db.json`) | Simulated, ephemeral data | low |
| Host process / runtime | Availability of the single-simulation slot | medium |

## 3. Entry points & trust boundaries

| entry_point | description | trust_boundary | reachable_assets |
|---|---|---|---|
| `POST /api/v1/simulation` | Accepts an untrusted OpenAPI spec | remote (semi-trusted) | specs, skills, LLM key (indirectly) |
| `POST /api/v1/simulation/reset` | Resets the active session | remote (semi-trusted) | session state |
| MCP `tools/call` (`/mcp`, `/mcp/sse`, `/mcp/messages`) | Drives the LLM agent per operation | remote (semi-trusted) | LLM key (indirectly), state store |
| Sidecar MCP server (`mcp_port`) | Optional second listener on a separate port | network | same as MCP transport |
| `config/harness.yaml` + `.env` | Startup configuration & secrets | local filesystem | LLM key |

## 4. Threats

| id | threat | actor | impact | likelihood | status |
|---|---|---|---|---|---|
| T1 | Malicious/oversized spec causes resource exhaustion (huge schemas, deep `$ref`) | remote semi-trusted | DoS | medium | partially_mitigated (spec validation; single-sim slot) |
| T2 | Prompt injection embedded in spec descriptions steers the LLM to emit attacker-controlled output | remote semi-trusted | data integrity / misleading responses | medium | partially_mitigated (responses are simulated, not executed; read-only FS backend) |
| T3 | `LLM_API_KEY` leaked via logs or error messages | any with log access | credential disclosure | low | partially_mitigated (secret kept out of YAML; detect-secrets in pre-commit) |
| T4 | Path traversal via spec-derived skill name writing outside `skills-store/` | remote semi-trusted | file overwrite | low | mitigated (operation-id/name sanitisation) |
| T5 | Unbounded concurrent calls exhaust the agent queue | remote semi-trusted | DoS | medium | mitigated (bounded FIFO queue → `concurrent_queue_full` 503) |
| T6 | Sidecar port bound to a public interface exposes the simulation | misconfiguration | unauthorized access | low | deprioritized (deployment responsibility) |
| T7 | Cost amplification: many tool calls drive up LLM spend | remote semi-trusted | financial | medium | partially_mitigated (`max_messages`, idle timeout) |

## 5. Deprioritized

| threat | reason |
|---|---|
| Multi-tenant isolation between simulations | Design invariant is one simulation per process; not a multi-tenant service |
| Authentication/authorization on the API | Out of scope — expected to run behind an internal gateway or on localhost |
| Network-level exposure of the sidecar | Deployment/operator responsibility, not enforced in-process |

## 6. Open questions

- Is there an enforced upper bound on submitted spec size / number of operations?
- Are LLM request/response bodies ever written to the per-process log files at debug level?
- Should per-session LLM token/cost budgets be enforced in addition to `max_messages`?

## 7. Provenance

- mode: bootstrap
- date: 2026-06-30
- maintainer: skillberry-ai/simulation-harness

## 8. Recommended mitigations

| mitigation | threat_ids | effort |
|---|---|---|
| Enforce a max spec size and operation count at the API boundary | T1, T7 | S |
| Add an explicit prompt-injection guard / output schema validation for simulated responses | T2 | M |
| Audit log statements to confirm `LLM_API_KEY` and request bodies are never logged | T3 | S |
| Document binding the sidecar to localhost by default in deployment docs | T6 | S |
| Add a per-session token/cost ceiling alongside `max_messages` | T7 | M |
