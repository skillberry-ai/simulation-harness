# Simulation Harness — Technical Requirements

This document captures the technical requirements and constraints for the Simulation Harness. It is the contract that the design (see [DESIGN.md](./DESIGN.md)) must satisfy. The user-facing motivation lives in [USER_NEED.md](./USER_NEED.md). Requirements specific to the alpha consumer are documented in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md), not here — this document describes the harness itself, independent of any particular consumer platform.

## 1. Functional Requirements

### 1.1 Granularity — Service-Level Simulation

- The unit of simulation is a **service**: a logically related set of tools described by a single OpenAPI specification (e.g., a travel-management service, a restaurant-reservation service, an HR system). The harness simulates the service as a whole, not individual tools in isolation.
- The skill-generation utility MUST accept an OpenAPI JSON describing all of a service's tools and emit **one skill** that covers that service. The agent loads that single skill at simulation creation.
- A future phase may add cross-service composition (multi-service skills); Phase 1 simulates exactly one service per harness instance.

### 1.2 Management Surface

- The harness MUST expose a REST API for management and configuration.
- The harness MUST support starting a simulation against a specified skills folder and OpenAPI spec.
- The harness MUST support resetting the simulation's singleton agent state on demand (see §1.7).
- The harness MUST support runtime configuration of the LLM provider/model used for simulation, with sensible defaults coming from the harness config file (see §1.6).
- Tool execution itself is **not** exposed via the management REST API in Phase 1 — all tool calls flow through the MCP surface (§1.3). A REST `/execute` endpoint is deferred past Phase 1; consumers that need direct REST access can be added when a concrete need exists.

### 1.3 MCP Server Surface

- The harness MUST expose its simulated service through an **MCP server**. This is the only tool-execution path in Phase 1, and the primary integration path for any consumer (agentic platform, optimization mechanism, agent at runtime).
- The MCP surface MUST support the two transports defined by the official MCP SDK at stable, documented URLs:
  - **SSE** at `GET /mcp/sse` (with companion `POST /mcp/messages`).
  - **Streamable HTTP** at `/mcp` (single ASGI mount).
- **Transport selection (Phase 1) — configured, not runtime.** Each harness instance runs **exactly one** of the two transports, chosen at process startup via the YAML configuration (`mcp.transport: sse | streamable_http`, §1.6). The other transport is not mounted and its routes return 404. There is no first-connection-wins race, no runtime switching, and no inter-transport lock. The Phase 1 single-session model already implies one consumer per instance; a configured choice is the simplest correct shape and keeps the wire surface deterministic.
- Lifting this to dual-transport (both running concurrently against one `mcp.server.Server`) is a **Phase 2** concern and MUST NOT be assumed by Phase 1 implementation code. Code paths that today depend on "one transport per process" (e.g., absence of cross-transport queue arbitration) are explicitly allowed and will be revisited when multi-session lands.
- The MCP surface MUST support standard MCP `tools/list` and `tools/call` semantics, so any MCP-capable client can consume it.
- The MCP surface itself is stateless at the protocol layer (Streamable HTTP runs in stateless mode — no `Mcp-Session-Id` negotiation); statefulness lives below MCP, in the simulation's singleton agent thread (§1.7).
- **Transport parity invariant**: although only one transport runs at a time in Phase 1, both transports MUST be implemented to be identical from the consumer's perspective modulo wire format and connection lifecycle — the choice between them is a deployment knob, not a feature gate. Parity covers, at minimum: the `tools/list` set and schemas; the `tools/call` result shape including the structured error payloads in §1.7; the session bookkeeping side-effects (counter increments, idle-clock updates, expiry behavior, queue admission). Any change that breaks this parity is a design change, not an implementation detail.

### 1.4 Skill Generation Utility Integration

- The harness MUST embed a skill-generation utility (copied from the existing `mcp-simulation` project, not imported as a dependency).
- The utility MUST take an inline OpenAPI JSON object describing a service and produce a single skill representing that service.
- The skill-generation utility MUST NOT carry its own configuration file. The upstream `utils/skill-creator/config.yaml` is dropped during the copy: LLM credentials, model, temperature, and `max_tokens` come from the harness's main YAML (§1.6) plus per-request overrides; the generation guide and system prompt are bundled with the harness as packaged assets, loaded by relative path from the adapted module.
- The skill-generation utility MUST accept the simulation name as a literal directory name under the skill folder (no `{api_name}-simulation` template expansion — the caller already chose the name in the create-simulation request).
- Skills MAY be generated either at build time / pre-deploy or at simulation creation. The reuse path (below) lets pre-generated skills be picked up without re-running generation; if no skill is present on disk, the harness generates one synchronously during `POST /api/v1/simulation`. Runtime *mutation* of an already-loaded skill remains out of scope (deferred to Phase 3).
- The harness MUST provide lifecycle handling for loaded skills (load at simulation start, list, release on simulation shutdown).
- **Skill reuse at initialization**: at simulation creation, the harness MUST check whether a skill has already been generated for the requested simulation name. The check is: a directory matching the simulation name exists under the configured skill folder, and that directory contains a `SKILL.md` file. If so, the harness MUST reuse the on-disk skill and skip regeneration. The caller MAY pass a `regenerate` (override) flag in the create-simulation request to force regeneration even when an existing skill is present; in that case the existing skill folder is overwritten. Mismatch between the on-disk skill and the OpenAPI spec passed in the request is the operator's responsibility — Phase 1 does not fingerprint the spec.
- **Reuse warning**: when reusing an on-disk skill, the harness MUST log a WARN naming the skill, its `SKILL.md` mtime, and reminding the operator to pass `regenerate: true` if the spec has changed. This is the Phase 1 mitigation for the no-fingerprint footgun; spec-hash comparison (`<skills_folder>/<name>/.spec.sha256`) is deferred to Phase 3.
- **Atomic skill writes**: skill generation MUST be atomic at the directory level. The generator writes into a temp directory that is a **sibling of the target** (under `skills_folder` itself, not `/tmp`) so the rename stays within one filesystem, then renames it to `<skills_folder>/<name>/` only on successful completion of all skill artifacts; if generation fails partway, the temp directory MUST be removed and no `<skills_folder>/<name>/SKILL.md` is left behind. This guarantees that the reuse check (presence of `SKILL.md`) cannot match a half-written skill.
- **Skill folder filesystem**: the harness requires read+write on `skills_folder` at startup. Multi-instance shared skill folders are out of scope for Phase 1 — each instance owns its own folder.

### 1.5 Deep Agent Reuse

- The harness MUST reuse the existing Deep Agent from `mcp-simulation` (LangChain + LangGraph based).
- Skills MUST be readable from the file system at simulation creation time.
- The agent MUST persist conversational/session state via the LangGraph checkpointer.
- A future iteration may refactor the Deep Agent; Phase 1 takes it as-is via copy-and-adapt.

### 1.6 Configuration File

- The harness MUST be configured via a **YAML configuration file**. The file is the source of truth for harness defaults.
- The configuration file MUST cover at least the following:
  - **API keys** for LLM providers — accepted either as literal values or as environment-variable references (the harness MUST support both forms; at least one must resolve to a non-empty key for the configured provider).
  - **API base URL** (`api_base`) — optional override for the LLM provider endpoint, accepted either as a literal value or as an environment-variable reference. Used for self-hosted deployments, gateways, and OpenAI-compatible providers. When unset, the SDK default applies.
  - **Default skill-generation model** — the model used by the skill-generation utility.
  - **Default simulation model** — the model used by the simulation deep agent at runtime. The runtime API MAY override this per-request.
  - **Default temperature** — the sampling temperature used by both the skill-generation utility and the simulation deep agent. Default value is `0`. The runtime API MAY override this per-request for the simulation model; the skill-generation temperature is taken from the YAML only.
  - **LLM provider** — the harness pins one provider per instance (set in the YAML, e.g. `openai`). The runtime API MAY override `model` and `temperature` per simulation but MUST NOT change the provider — credentials are bound to the provider at startup.
  - **Skill folder** — the directory where generated skills are stored and from which the agent loads them at simulation creation.
  - **Maximum session length** — an upper bound on the number of MCP `tools/call` invocations in the singleton session before it is considered expired (§1.7). Phase 1 measures session length in tool calls, not tokens or LangGraph state messages — simpler and provider-independent.
  - **Idle timeout** — an upper bound, in seconds, on how long the singleton session may sit without a tool call before it is considered expired (§1.7).
  - **Maximum concurrent queue depth** — an upper bound on the number of `tools/call` invocations (in-flight + waiting) the harness will admit against the singleton thread before rejecting (§1.7). Default `8`.
  - **MCP transport** (`mcp.transport`) — selects which MCP transport this instance mounts. One of `sse` or `streamable_http`; no default (operator MUST choose). The non-selected transport's routes return 404. See §1.3.
- The harness MUST refuse to start if the configuration file is missing, unparseable, or fails validation against the documented schema.
- **Configuration lifecycle**: the YAML is read once at process startup. Configuration changes (LLM credentials, models, session limits, skill folder, queue depth) require a process restart. Phase 1 does NOT support hot-reload; in-flight simulations terminate when the process exits.

### 1.7 Singleton Session Model

- A harness instance hosts exactly one stateful agent thread for the lifetime of the simulation. All MCP `tools/call` invocations land on this single thread, so context accumulates across tool calls.
- The thread identifier is internal to the harness — it is never carried in MCP requests or returned to consumers.
- The session is considered **expired** when any of the following occurs:
  1. The number of `tools/call` invocations on the current thread exceeds the configured `max_messages` (§1.6).
  2. The wall-clock interval since the last `tools/call` exceeds the configured `idle_timeout_seconds` (§1.6).
  3. The operator calls `POST /api/v1/simulation/reset`.
- On expiry due to (1) or (2), the harness MUST fail the offending tool call with an MCP `isError: true` result indicating the session expired, and MUST then reset the thread so that the next tool call starts on a fresh context. (Fail-then-reset, not silent auto-reset — a consumer rehearsing a multi-step plan must be able to detect that continuity broke.) The result payload MUST include a structured `reason` (`max_messages_exceeded` or `idle_timeout_exceeded`) and the relevant limit/observed values so consumers can branch programmatically.
- **Queue-on-expiry behavior**: the queue dies with the session. When expiry fires, the in-flight call receives the expiry error (`max_messages_exceeded` or `idle_timeout_exceeded`) and EVERY call already waiting in the FIFO queue MUST be failed with the **same** structured error shape — `reason: "max_messages_exceeded"` or `reason: "idle_timeout_exceeded"` — not a generic "cancelled" or "queue drained". Only after the queue is drained does the harness reset the thread. The next call to arrive (post-expiry) lands on the fresh thread normally. Rationale: a consumer that fired a small batch of calls sees a uniform failure shape across the whole batch, so its retry/recovery logic does not need a separate "I was queued when someone else expired the session" branch.
- The idle-timeout check is evaluated **at the moment a queued call acquires the lock**, against the timestamp of the last successful call — not at the moment the call entered the queue. A call that waits longer than `idle_timeout_seconds` for the lock therefore fails with `idle_timeout_exceeded`, not silently succeeds, and triggers the queue-drain rule above.
- Concurrency: the harness MUST serialize tool calls against the singleton thread (no interleaving inside the agent). Phase 1 implements this as a **bounded FIFO queue**: an arriving call waits for the in-flight call to finish; an arriving call that would push the queue past `max_concurrent_queue_depth` (§1.6) MUST be rejected with an MCP `isError: true` result and `reason: "concurrent_queue_full"`. The counter and idle clock MUST NOT be advanced for a queue-overflow rejection. Phase 1 documents itself as single-tenant per instance; deploy more instances for concurrent users.
- **Failure semantics for `tools/call`** (non-expiry, non-overflow): LLM-provider errors and tool-invocation errors MUST surface as MCP `isError: true` results with structured reasons (`llm_provider_error`, `tool_invocation_error`, `internal_error`). The counter and idle clock MUST NOT be advanced for a failed call (a failed call does not burn a `max_messages` slot and does not reset the idle window). Thread state MUST be preserved at the last LangGraph checkpoint so the next call can resume coherently. The harness MUST NOT auto-retry; retry policy is a consumer concern.
- The idle-timer clock starts at the **first** tool call after creation or reset (not at simulation creation), so a quiet simulation does not expire before its first use.
- **Live session counters** MUST be exposed via `GET /api/v1/simulation` (tool-call count, max_messages, seconds_since_last_call, idle_timeout_seconds, queue_depth, max_concurrent_queue_depth) so consumers can manage their session lifecycle proactively without inventing MCP-level metadata.

### 1.8 Multi-Service Simulation (Future Extension)

- The Phase 1 surface MUST be designed so that simulation across multiple services (composition / multi-service skills) can be added later without rearchitecture.
- Phase 1 itself only simulates one service per instance.

### 1.9 Standalone, Platform-Agnostic Project

- The harness MUST be a standalone Python project. Components from `mcp-simulation` are copied and adapted, NOT imported as a package dependency.
- The harness MUST be agnostic to the consumer platform. It MUST NOT embed assumptions about any particular agentic platform's data model, schema, auth model, or UI.
- Per-platform integration details (e.g., how a platform registers the harness's MCP URL in its tool catalog) belong in that platform's documentation or in a per-platform integration guide — not in the harness itself.
- The harness MAY depend on the official Model Context Protocol SDK (`mcp` Python package) and on shared third-party libraries (LangChain, LangGraph, FastAPI, etc.).

## 2. Non-Functional Requirements

### 2.1 Performance

- **Phase 1**: no hard latency SLO. Per-request latency is dominated by the chosen LLM and is observable through normal logs.
- A latency SLO is to be set in a later phase once telemetry is available.

### 2.2 Reliability

- Failure of simulation creation (bad OpenAPI spec, missing skills, bad credentials, invalid config) MUST return a 4xx/5xx synchronously and leave the harness in a clean, retry-able state.

### 2.3 Deferred to a Later Phase

The following concerns are explicitly **deferred** past Phase 1. Phase 1 design choices should not foreclose them, but no Phase 1 implementation work is expected:

- **Scalability** — concurrent-session targets, multi-instance orchestration, per-instance cost optimization. Phase 1 supports a small number of concurrent sessions on a single instance and is not benchmarked.
- **Security** — authentication (bearer tokens, per-caller API keys), secret-handling policy, audit logging. Phase 1 endpoints are unauthenticated; deployments are expected to rely on network-level isolation (cluster-internal only, localhost, etc.) until security is reintroduced.
- **Observability** — Prometheus metrics, structured-log requirements, OpenTelemetry tracing. Phase 1 emits ordinary application logs; metrics/tracing/spend telemetry are deferred. Phase 1 DOES require a minimal per-tool-call log line (see §2.4) so an operator can debug a failed `tools/call` without metrics infrastructure — that is the floor, not a richer observability surface.
- **Cost controls** — application-level rate limiting and spend caps. Phase 1 relies on the upstream LLM key's own cap.

These deferrals are intentional Phase 1 scope decisions and are tracked in §4.

### 2.4 Phase 1 Logging Floor

Phase 1 ships without metrics, tracing, or token-spend telemetry — but the harness MUST emit **one structured log line per `tools/call`** so an operator can answer "why did this Try fail?" without external systems. The line MUST include, at minimum:

- `tool_name` — the MCP tool name invoked.
- `outcome` — one of `success`, `max_messages_exceeded`, `idle_timeout_exceeded`, `concurrent_queue_full`, `llm_provider_error`, `tool_invocation_error`, `internal_error` (i.e., the same `reason` taxonomy as the MCP error payloads in §1.7).
- `duration_ms` — wall-clock duration of the call inside the harness, including queue wait.
- `tool_call_count` — the post-call value of the singleton-session counter (or pre-call, for failed calls — the value MUST be unambiguous and consistent with §1.7's "counter advances only on success" rule).
- `queue_depth_at_admission` — the number of calls queued (in-flight + waiting) when this call entered the queue.
- `token_usage` — provider-reported prompt/completion/total token counts when the LLM call ran, or `null` when no LLM call ran (queue overflow, expiry-without-LLM-call). Phase 1 does not aggregate these; the per-call line is sufficient for spot debugging.
- `transport` — `sse` or `streamable_http`, matching `mcp.transport` (§1.6). Constant for the life of the process; logged for completeness so a single greppable line tells the full story.

The format MAY be plain key=value or JSON; consistency across calls is what matters. Anything richer (aggregated metrics, dashboards, alerts) is Phase 4 work and MUST NOT be a Phase 1 dependency.

## 3. Constraints and Compatibility

- **MCP protocol**: the harness's MCP surface MUST conform to the standard Model Context Protocol so any MCP-capable consumer can call it without bespoke adapters.
- **One simulation per harness instance**: each MCP endpoint serves exactly one simulated service. Multi-service orchestration is delegated to the deployment layer (typically Kubernetes), not the harness. This keeps the MCP URL→simulation mapping unambiguous: the URL *is* the simulation identifier.
- **Compatibility with `mcp-simulation` patterns**: copied components (Deep Agent, OpenAPI parsing, prompts, skill generator) MUST remain semantically equivalent to their upstream counterparts at copy time. Divergence after that point is allowed and expected.
- **No vendored MCP**: the harness uses the official `mcp` Python SDK directly. It does not vendor an MCP implementation.

## 4. Phase 1 Scope Decisions (Authoritative)

These decisions narrow Phase 1 scope to ship the alpha. Later phases may revisit them.

| Decision | Choice | Rationale |
|---|---|---|
| **Granularity** | Service (one OpenAPI spec → one skill → one simulation per instance). | Matches how skills are actually authored and consumed. Removes ambiguity around "tool-level vs skill-level". |
| **MCP routing model** | One simulation per harness instance. An instance hosts exactly one OpenAPI spec / one skill / one MCP server. | Keeps the MCP URL→simulation mapping unambiguous and pushes orchestration to the deployment layer. Many MCP consumers route by URL only and have nowhere to encode a simulation ID. |
| **Tool execution surface** | MCP `tools/call` only in Phase 1. The REST `/api/v1/execute` and `/chat` endpoints are both deferred. | The primary integration path is MCP, and all Phase 1 consumers (Skillberry alpha, Use Case 2 optimizer, Use Case 3 rehearsal) speak MCP. Removing the REST execute path also removes session-id plumbing from the surface — statefulness now lives behind a single implicit thread (§1.7). |
| **Session model** | Singleton stateful thread per harness instance, expired by tool-call cap, idle timeout, or explicit `/reset`. Fail-then-reset on expiry. Calls serialized via a bounded FIFO queue (default depth 8). | Use Cases 2 and 3 need multi-call coherence within a simulation; Use Case 1 doesn't care. One-instance-one-thread is the simplest shape that satisfies all three (§1.7). The bounded queue makes the rejection-vs-queueing decision definitive instead of leaving it as an implementation detail. |
| **Configuration lifecycle** | Read once at startup. Changes require a process restart. No hot-reload in Phase 1. | Hot-reload is non-trivial for LLM credentials/provider (bound to the agent at construction). Restart-only is the simplest correct semantics; hot-reload reappears in Phase 4. |
| **OpenAPI validation depth** | Schema validation only (`openapi-spec-validator`); 3.0.x and 3.1.x accepted; 10 MB body cap; failures return 422. | Custom semantic validation can come back when a concrete need emerges. The validator's built-in checks (operationId uniqueness, `$ref` resolution) are sufficient for Phase 1. |
| **Runtime skill changes** | Not supported in Phase 1. Skills are loaded at simulation startup. | The deep agent reads `skills_folder` once at init. Hot-reload would require recreating the agent or upstream changes to `deepagents`. |
| **Simulation lifecycle** | Dynamic via management API. The deployer (or an automation script) calls `POST /api/v1/simulation` once per instance with the OpenAPI spec. | Decouples harness deploys from new services while staying explicit. With one simulation per instance: deploy → POST /simulation once → MCP endpoint goes live. |
| **Configuration source** | YAML config file (see §1.6). Defaults for skill-gen model, simulation model, skill folder, session limits, and API keys live there. | Single source of truth. Operators edit one file; runtime overrides are optional, not required. |
| **Default LLM model** | Defaults come from the YAML config file. Operators MAY override per-simulation through the management API; if they don't, the YAML defaults apply. | The previous "no default — operator must specify" rule was relocated into config: the default lives in the YAML the operator already edits. Less ceremony, same deliberate-choice property. |
| **Authentication** | Deferred. Phase 1 endpoints are unauthenticated and rely on network-level isolation. | Closed alpha; security is deferred (§2.3). |
| **Latency SLO** | None in Phase 1. | Latency is dominated by the chosen LLM; setting an SLO without telemetry would be guesswork. |
| **Scalability target** | None specified for Phase 1. | Deferred (§2.3). |
| **Observability** | Ordinary application logs only. No metrics, tracing, or token-spend telemetry required. | Deferred (§2.3). |
| **Rate limiting / cost caps** | Deferred. Phase 1 relies on upstream LLM key caps. | Closed alpha; not worth the implementation cost yet. |

### 4.1 OpenAPI Spec Input Shape

- `POST /api/v1/simulation` accepts the OpenAPI spec as an **inline JSON object** in the request body. URL fetch, multipart upload, and local file path are out of scope for Phase 1; they may be added later as additional input shapes without breaking the inline-object form.
- **Validation depth**: schema validation via `openapi-spec-validator`. Both OpenAPI 3.0.x and 3.1.x MUST be accepted. Semantic validation is limited to what the validator already performs (operationId uniqueness, `$ref` resolution); no custom Phase 1 semantic checks beyond those.
- **Size limit**: the request body MUST be capped at 10 MB; oversize requests are rejected with HTTP 413 before parsing.
- A spec that fails OpenAPI validation MUST cause `POST /api/v1/simulation` to return 422 with a structured error pointing to the failing path/keyword, and leave the harness in its prior state (no simulation created, no partial skill written — see §1.4 atomic write).

## 5. Out of Scope (Phase 1)

- Runtime skill generation or hot-reload.
- The conversational `/chat` endpoint.
- Direct REST tool execution (`/api/v1/execute`) and any caller-supplied `session_id`. Tool execution is MCP-only in Phase 1.
- Multiple concurrent sessions per harness instance (Phase 1 is single-tenant per instance; deploy more instances to scale).
- Configuration hot-reload. Phase 1 reads the YAML once at startup; changes require a process restart.
- Multi-instance shared `skills_folder` (read-only skill cache across instances). Each instance owns its own folder in Phase 1.
- Custom OpenAPI semantic validation beyond what `openapi-spec-validator` already performs.
- Spec fingerprinting against on-disk skills (`<skills_folder>/<name>/.spec.sha256`). Phase 1 logs a WARN on every reuse instead.
- Per-call wait timeout for queued `tools/call` invocations. Queued calls wait indefinitely; the session-level idle timeout still governs the session as a whole.
- MCP protocol-level session negotiation (`Mcp-Session-Id`).
- Multi-simulation hosting in a single process.
- Multi-service simulation (composition across services).
- Multi-tenant isolation, per-tenant quotas, billing.
- MCP-level session negotiation (`Mcp-Session-Id`). The streamable-HTTP transport runs stateless in Phase 1.
- MCP stdio transport. SSE and streamable-HTTP only.
- OpenAPI spec input via URL fetch, multipart upload, or local path. Inline JSON object only in Phase 1.
- Per-simulation LLM provider override. The provider is fixed by the YAML at startup; the API may override `model` and `temperature` only.
- Persistent storage beyond the in-memory LangGraph checkpointer.
- Authentication (bearer tokens, per-caller API keys).
- Prometheus metrics, OpenTelemetry tracing, structured-log mandates.
- Application-level rate limiting and cost caps.
- Any consumer-platform-specific integration code (those live in the consumer or in a per-platform integration guide).

## 6. Acceptance Criteria (Phase 1)

The harness itself (consumer-agnostic):

- [ ] Load and validate the YAML config file at startup; refuse to start on a missing/invalid file.
- [ ] Create the (one) simulation from an OpenAPI spec via `POST /api/v1/simulation`, using the YAML defaults for skill-gen model, simulation model, and skill folder unless the request overrides them.
- [ ] Generate a single service-level skill from an OpenAPI JSON via the build-time skill-generation utility, drop it in the configured skill folder, and have the agent load it at simulation creation.
- [ ] On `POST /api/v1/simulation`, reuse an existing `<skills_folder>/<name>/SKILL.md` instead of regenerating; regenerate only when the request sets the `regenerate` override flag.
- [ ] Execute tools via MCP `tools/call` over the SSE transport (`/mcp/sse` + `/mcp/messages`), against the singleton stateful thread.
- [ ] Execute tools via MCP `tools/call` over the streamable-HTTP transport (mounted at `/mcp`), against the same singleton stateful thread. Both transports share one underlying `mcp.server.Server`.
- [ ] Transport parity: the same `tools/list` + `tools/call` sequence over SSE and Streamable HTTP produces identical tool sets, identical result shapes (including structured error payloads), and identical session bookkeeping side-effects (counter, idle clock, queue admission).
- [ ] Multi-call coherence: a sequence of MCP `tools/call` invocations against one harness instance shares accumulated context (verifiable by a follow-up call referencing prior state).
- [ ] `POST /api/v1/simulation/reset` clears the singleton thread; the next tool call starts fresh.
- [ ] Enforce the configured `max_messages` (tool-call count) and `idle_timeout_seconds`. The call that would breach the limit fails with an MCP `isError: true` result carrying a structured payload (`reason: "max_messages_exceeded" | "idle_timeout_exceeded"`, plus `limit` and `observed`), and the thread is then reset so the following call starts fresh.
- [ ] Counter and idle clock advance only on success: a failed `tools/call` (LLM-provider error, tool-invocation error) does not burn a `max_messages` slot and does not reset the idle window; thread state is preserved at the last LangGraph checkpoint.
- [ ] Concurrent MCP `tools/call` invocations against the same harness instance are serialized via a bounded FIFO queue (default depth `sessions.max_concurrent_queue_depth: 8`); arrivals exceeding the cap are rejected with an MCP `isError: true` result, `reason: "concurrent_queue_full"`, with no counter/idle-clock side-effect.
- [ ] `GET /api/v1/simulation` exposes a `session` block with `tool_call_count`, `max_messages`, `seconds_since_last_call`, `idle_timeout_seconds`, `queue_depth`, and `max_concurrent_queue_depth`.
- [ ] Skill reuse logs a WARN at simulation creation naming the reused skill, its `SKILL.md` mtime, and reminding the operator to pass `regenerate: true` if the spec has changed.
- [ ] OpenAPI spec validation accepts both 3.0.x and 3.1.x via `openapi-spec-validator`; the request body is capped at 10 MB; validation failures return 422 with a structured error.

Consumer integration acceptance is documented per-consumer. The alpha consumer's acceptance criteria are in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md).
