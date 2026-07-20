# Simulation Harness — Design Document

This document describes the architecture and component design of the Simulation Harness. It assumes the user need ([USER_NEED.md](./USER_NEED.md)) and technical requirements ([REQUIREMENTS.md](./REQUIREMENTS.md)) as inputs and treats their Phase 1 scope decisions ([REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative)) as authoritative. The concrete alpha integration is described in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md).

## 1. Executive Summary

The Simulation Harness is a FastAPI-based service that provides a managed environment for simulating an MCP **service** (a logically related set of tools described by a single OpenAPI spec). It is a **standalone project** that copies and adapts components from the existing `mcp-simulation` project, adding a REST API layer for runtime configuration and lifecycle management, plus an MCP server surface that any MCP-capable consumer can call.

**Key insight**: by exposing the simulation as a standard MCP server, the harness plugs into the same execution path a real service backend would — no consumer-specific integration code is needed. The harness is platform-agnostic; the alpha consumer is one such platform, but the design does not depend on it. See [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md) for the alpha-specific instance.

The harness is configured by a single YAML file (LLM API keys, default models, skill folder, session limits — see §9). Phase 1 defers security, scalability targets, and observability instrumentation; the harness runs unauthenticated behind network-level isolation and emits ordinary application logs ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)).

## 2. Architecture Overview

A single harness process hosts **one** simulation of **one** service. Multi-simulation and multi-service composition are out of scope ([REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative)) — multiple simulations are achieved by running multiple harness instances (e.g., one Kubernetes pod per simulated service).

```
┌─────────────────────────────────────────────────────────────┐
│              Simulation Harness  (one instance)              │
│                    (FastAPI + MCP)                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────────────────┐    ┌───────────────┐ │
│  │  Management API                  │    │  MCP          │ │
│  │ POST /api/v1/simulation          │    │ /mcp/sse  SSE │ │
│  │ GET  /api/v1/simulation          │    │ /mcp/messages │ │
│  │ DELETE /api/v1/simulation        │    │ /mcp      HTTP│ │
│  │ POST /api/v1/simulation/reset    │    │ (stateless)   │ │
│  └────────┬─────────────────────────┘    └───────┬───────┘ │
│           │                                       │        │
│           └───────────────────┬───────────────────┘        │
│                               │                            │
│                ┌──────────────▼─────────────┐              │
│                │   Simulation Instance      │              │
│                │   (singleton this process) │              │
│                │   - Skills loaded at init  │              │
│                │   - LangGraph checkpointer │              │
│                │   - One implicit thread    │              │
│                │   - Tool-call counter      │              │
│                │   - Idle timer             │              │
│                │   - Serializing lock       │              │
│                └──────────────┬─────────────┘              │
│                              │                               │
│                ┌─────────────▼──────────────┐                │
│                │  Deep Agent (copied from   │                │
│                │  mcp-simulation, adapted)  │                │
│                └────────────────────────────┘                │
│                                                               │
└─────────────────────────────────────────────────────────────┘

Lifecycle:
  instance start → POST /api/v1/simulation (one-time) → MCP endpoint live → execute calls
  instance stop  → simulation gone (no persistence in Phase 1)
```

## 3. Consumer Integration Pattern

In Phase 1, the only tool-execution path is MCP. The management REST API exists alongside MCP for lifecycle (create / get / delete / reset the simulation) but does not execute tools — see [REQUIREMENTS.md §1.2](./REQUIREMENTS.md#12-management-surface).

```
┌─────────────────┐
│    Consumer     │
│ (MCP-capable)   │
└────────┬────────┘
         │ MCP Protocol (SSE) — tools/list, tools/call
         ▼
┌─────────────────┐
│   Simulation    │
│    Harness      │
│  (MCP Server)   │
└─────────────────┘
```

**Why MCP-only**:
1. Any MCP-capable consumer (an agentic platform, an optimization mechanism, an agent at runtime) can call the harness without bespoke integration code.
2. Simulated tools appear identical in shape to real tools — same protocol, same call semantics — so the consumer can swap simulation for production by changing only the URL.
3. The harness stays platform-agnostic: it speaks an open protocol rather than any one platform's tool-execution API.
4. Removing a parallel REST execute path also removes session-id plumbing from the public surface; statefulness is handled by a single implicit thread inside the harness ([§5.2](#52-simulation-instance)).

A direct REST `/execute` endpoint is **deferred past Phase 1** — testing/debugging is covered by the example MCP client in `examples/mcp-client/`. If a future Pattern A consumer materializes, the endpoint can be added without disturbing the singleton-thread model.

The harness imposes no opinions about *how* a consumer obtains the MCP URL or wires it into its own tool catalog — that belongs in the consumer's documentation. For a worked example, see [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md).

## 4. API Design

> Per [REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative): a harness process hosts exactly one simulation of one service. Endpoints are NOT parameterized by `simulation_id` — there is only one. Skill management endpoints, the conversational chat endpoint, and the REST `/execute` endpoint are all deferred past Phase 1. Tool execution in Phase 1 flows exclusively through MCP `tools/call` ([§3](#3-consumer-integration-pattern)).
>
> **Auth**: deferred. Phase 1 endpoints are unauthenticated and rely on network-level isolation ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)).
>
> **Defaults**: `llm_config.model`, the skill-generation model, and `skills_folder` all default to values from the harness YAML config ([§9](#9-configuration)). Request fields that override them are optional.

### 4.0 Error Envelope (single shape across the management API)

All Phase 1 management-API failure responses use one envelope, so a consumer parses one shape:

```json
{
  "error": {
    "code": "openapi_invalid",
    "message": "schema validation failed at paths./flights.get",
    "details": { "...optional, code-specific..." }
  }
}
```

`code` is one of:

| `code` | HTTP status | When |
|---|---|---|
| `simulation_already_exists` | 409 | `POST /simulation` while one is running |
| `simulation_not_found` | 404 | `GET`/`DELETE`/`reset` with no simulation |
| `openapi_invalid` | 422 | OpenAPI spec fails validator; `details.path`, `details.keyword` populated |
| `openapi_too_large` | 413 | Request body > 10 MB |
| `provider_override_rejected` | 422 | `llm_config.provider` set on `POST /simulation` |
| `config_invalid` | 422 | Other request-body validation (Pydantic) failures |
| `skill_generation_failed` | 502 | Generation LLM call failed; `details.upstream_status` may be set |
| `skill_filesystem_error` | 500 | Atomic write / rename / cleanup failed; `details.errno` may be set |
| `internal_error` | 500 | Anything else uncategorized |

MCP `tools/call` failures use a separate envelope (the MCP `isError: true` result with the `reason` taxonomy from §5.2.1) and do NOT use this shape. The two envelopes serve different audiences: management is for the operator, MCP errors are for the consumer's tool-call retry logic.

Phase 2+ MAY extend the `code` enum (for new failure modes) but MUST NOT change the envelope shape; that would break consumer parsers. New codes are additive.

### 4.1 Management API

#### POST /api/v1/simulation

Create the simulation. Returns `409 Conflict` if one already exists; the caller must `DELETE` it first to replace.

**Request:**
```json
{
  "name": "flight-booking-sim",
  "openapi_spec": { "openapi": "3.0.0", "info": {"title": "Flight Booking", "version": "1.0.0"}, "paths": { "...": "..." } },
  "skills_folder": "/path/to/skills",
  "regenerate": false,
  "llm_config": {
    "model": "gpt-4o-mini",
    "temperature": 0
  }
}
```

`skills_folder`, `regenerate`, and `llm_config` are optional; if omitted, `skills_folder` and `llm_config` fall back to the YAML config defaults ([§9](#9-configuration)) and `regenerate` defaults to `false`.

`openapi_spec` is an **inline JSON object** (not a URL string, file path, or upload) — see [REQUIREMENTS.md §4.1](./REQUIREMENTS.md#41-openapi-spec-input-shape). The OpenAPI spec describes a single service; the harness generates one service-level skill from it.

`llm_config` may override `model` and `temperature` only. The provider is fixed at process startup by the YAML and cannot be changed per simulation (credentials are bound to the provider). Attempts to set `provider` in `llm_config` MUST return 4xx.

**Skill reuse**: at initialization, the harness looks for `<skills_folder>/<name>/SKILL.md`. If it exists, the harness loads that skill and skips generation. If `regenerate: true` is set, the harness regenerates the skill (overwriting the existing folder) regardless of what's on disk. The harness does NOT fingerprint the OpenAPI spec against an existing skill; if the operator changes the spec but reuses the same name, they MUST pass `regenerate: true`.

**Response:**
```json
{
  "name": "flight-booking-sim",
  "status": "running",
  "tools": ["searchFlights", "bookFlight", "cancelBooking"],
  "created_at": "2026-05-29T18:00:00Z"
}
```

Initialization is synchronous from the caller's perspective — by the time this returns 200, the MCP endpoint is live and tools are listable. If anything fails (bad OpenAPI spec, missing skill files, LLM credentials), the call returns 4xx/5xx and no simulation is created.

#### GET /api/v1/simulation

Get simulation status and metadata. Returns `404 Not Found` if no simulation has been created yet.

**Response:**
```json
{
  "name": "flight-booking-sim",
  "status": "running",
  "tools": ["searchFlights", "bookFlight", "cancelBooking"],
  "created_at": "2026-05-29T18:00:00Z",
  "updated_at": "2026-05-29T18:05:00Z",
  "session": {
    "tool_call_count": 12,
    "max_messages": 200,
    "seconds_since_last_call": 47.3,
    "idle_timeout_seconds": 1800,
    "queue_depth": 0,
    "max_concurrent_queue_depth": 8
  }
}
```

The `session` block exposes the singleton-thread bookkeeping kept inside `SimulationInstance` (§5.2). It lets a consumer manage its session lifecycle proactively — e.g., issue a `/reset` before approaching `max_messages` — without having to invent MCP-level metadata. `seconds_since_last_call` is `null` until the first tool call lands. `queue_depth` is the number of `tools/call` invocations currently waiting on the serializing lock (§5.2); it is 0 in steady state.

#### DELETE /api/v1/simulation

Stop and remove the simulation. After this, `POST /api/v1/simulation` can be called again to create a new one. The MCP endpoint stops listing tools.

#### POST /api/v1/simulation/reset

Reset the singleton agent thread for this simulation. After this returns, the next MCP `tools/call` starts on a fresh agent context with the message counter and idle timer cleared.

**Request:** empty body (`{}`). There is no `session_id` — Phase 1 has exactly one implicit session per harness instance ([REQUIREMENTS.md §1.7](./REQUIREMENTS.md#17-singleton-session-model)).

**Response:** 200 with the simulation status object (same shape as `GET /api/v1/simulation`).

**Note**: `/reset` is also the operator's recovery path when a `tools/call` fails with a session-expired error (limit breached); calling it is optional in that case since the harness auto-resets after returning the error, but it is supported for symmetry.

### 4.2 Skill Management API — DEFERRED (post-Phase 1)

Per [REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative), runtime skill add/regen is not in Phase 1. Skills are loaded once at simulation creation from `skills_folder`. The endpoints sketched here are kept as a reference for a later phase:

- `POST /api/v1/simulation/skills` — generate and add a new skill at runtime
- `GET /api/v1/simulation/skills` — list loaded skills
- `DELETE /api/v1/simulation/skills/{skill_id}` — remove a skill

In Phase 1 these return `501 Not Implemented` (or are simply absent from the router).

### 4.3 Tool Execution — DEFERRED at the REST layer (post-Phase 1)

The Phase 1 tool-execution path is MCP `tools/call` over `/mcp/sse`. Per [REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative):

- `POST /api/v1/simulation/execute` — direct REST tool execution. **Deferred.** Re-introduce when a Pattern A consumer materializes.
- `POST /api/v1/simulation/chat` — conversational endpoint. **Deferred.** (`SimulatorAgent.generate_response` requires a tool name; building a chat surface is genuine adaptation work.)
- `GET /api/v1/simulation/sessions/{session_id}` — per-session inspection. **Removed.** Phase 1 has one implicit session; if a debug surface for it is needed later, `GET /api/v1/simulation` already returns simulation-level status and can be extended with a `session` block.

In Phase 1 these endpoints are simply absent from the router; consumers receive 404. The singleton-session state (tool-call count, last-activity timestamp) lives inside `SimulationInstance` (§5.2) and is not exposed over HTTP.

## 5. Component Design

### 5.1 Simulation Host

**Responsibilities:**
- Hold the (at most one) `SimulationInstance` for this process.
- Handle simulation create/delete lifecycle.
- Reject create when one already exists (409).

```python
class SimulationHost:
    """Holds at most one SimulationInstance per process."""

    def __init__(self, config: HarnessConfig):
        self.simulation: Optional[SimulationInstance] = None
        self.config = config
        # Serializes create/delete so concurrent POSTs and DELETE+POST races
        # cannot leave the host in a half-initialized or double-created state.
        self._lifecycle_lock = asyncio.Lock()

    async def create_simulation(self, spec: SimulationSpec) -> SimulationInstance:
        async with self._lifecycle_lock:
            if self.simulation is not None:
                raise SimulationAlreadyExistsError()  # → 409
            self.simulation = await SimulationInstance.create(spec, self.config)
            return self.simulation

    def get_simulation(self) -> SimulationInstance:
        if self.simulation is None:
            raise SimulationNotFoundError()
        return self.simulation

    async def stop_simulation(self) -> None:
        async with self._lifecycle_lock:
            if self.simulation is not None:
                await self.simulation.shutdown()
                self.simulation = None
```

Two simultaneous `POST /api/v1/simulation` calls serialize on `_lifecycle_lock`: the first creates, the second observes `simulation is not None` and gets a 409. A `DELETE` racing with a `POST` likewise cannot interleave. The lock is held only across the create/delete flow — `tools/call` execution does not contend for it (that's the per-instance lock in §5.2).

### 5.2 Simulation Instance

**Responsibilities:**
- Wrap the copied/adapted Deep Agent from `mcp-simulation`.
- Hold the singleton stateful thread (one implicit `thread_id`, never exposed).
- Enforce the tool-call cap and idle timeout against that thread (fail-then-reset on breach).
- Serialize concurrent `tools/call` invocations against the agent.

```python
class SessionExpiredError(Exception):
    """Raised when a tool call would exceed max_messages or idle timeout."""

_THREAD_ID = "default"  # internal; never exposed to consumers

class SimulationInstance:
    """Single simulation in this process, with one implicit stateful thread."""

    def __init__(
        self,
        config: SimulatorConfig,
        agent: SimulatorAgent,  # copied & adapted from mcp-simulation
        max_messages: int,
        idle_timeout_seconds: float,
    ):
        self.config = config
        self.agent = agent
        self.max_messages = max_messages
        self.idle_timeout_seconds = idle_timeout_seconds

        # Singleton-session state — guarded by self._lock.
        self._lock = asyncio.Lock()
        self._tool_call_count = 0
        self._last_activity_monotonic: Optional[float] = None  # None until first call

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Execute a tool against the singleton thread.

        Concurrency: serialized via self._lock (REQUIREMENTS §1.7). No two
        tool calls run inside the agent at the same time.

        Expiry: if max_messages or idle_timeout would be exceeded, the call
        fails with SessionExpiredError and the thread is reset so the next
        call starts fresh (fail-then-reset, not silent auto-reset).
        """
        async with self._lock:
            now = time.monotonic()

            # Idle-timeout check — only meaningful after the first call.
            if (
                self._last_activity_monotonic is not None
                and now - self._last_activity_monotonic > self.idle_timeout_seconds
            ):
                await self._reset_thread()
                raise SessionExpiredError("idle timeout exceeded; session reset")

            # Tool-call cap check.
            if self._tool_call_count >= self.max_messages:
                await self._reset_thread()
                raise SessionExpiredError("max_messages exceeded; session reset")

            # Run the call. Increment + stamp clock only on success — a failed
            # LLM call shouldn't burn a slot or hide a real idle period.
            result = await self.agent.generate_response(
                tool_name=tool_name,
                arguments=arguments,
                thread_id=_THREAD_ID,
            )
            self._tool_call_count += 1
            self._last_activity_monotonic = time.monotonic()
            return result

    async def reset(self) -> None:
        """Operator-initiated reset (POST /api/v1/simulation/reset)."""
        async with self._lock:
            await self._reset_thread()

    async def _reset_thread(self) -> None:
        """Wipe agent state for the singleton thread. Caller holds the lock."""
        await self.agent.reset(thread_id=_THREAD_ID)
        self._tool_call_count = 0
        self._last_activity_monotonic = None
```

The MCP server adapter translates `SessionExpiredError` into an MCP tool-call error (a result with `isError: true` and a structured payload — see §5.2.1). The next `tools/call` after that error executes against a fresh thread.

`SkillRegistry` runtime mutation and the `/chat` endpoint remain out of scope ([REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative)). The agent's `skills_folder` is loaded once at `SimulatorAgent.__init__`.

#### 5.2.1 Failure Semantics for `tools/call`

The harness distinguishes three failure modes on `tools/call`. All three surface as MCP `isError: true` results with a structured payload `{ reason, ... }`; none of them propagate as HTTP 5xx through the MCP transport — the transport call itself succeeded, the tool result is the failure.

| Mode | `reason` | Counter / idle clock | Thread state | Auto-retry |
|---|---|---|---|---|
| Session expiry — message cap | `max_messages_exceeded` | counter reaches limit; reset to 0 on fail-then-reset | reset (fresh on next call) | no |
| Session expiry — idle | `idle_timeout_exceeded` | last-activity older than limit; reset on fail-then-reset | reset | no |
| Concurrent queue overflow | `concurrent_queue_full` | unchanged | unchanged | no |
| LLM provider error | `llm_provider_error` | unchanged (no slot burned, no idle reset) | preserved at last LangGraph checkpoint | no |
| Tool-invocation error inside the agent | `tool_invocation_error` | unchanged | preserved at last LangGraph checkpoint | no |
| Anything else | `internal_error` | unchanged | preserved at last LangGraph checkpoint | no |

Key invariants:

- **Counter and idle clock are advanced only on success** (the `self._tool_call_count += 1` line in `execute_tool` runs after `agent.generate_response` returns without raising). A failed call does not burn a `max_messages` slot and does not reset the idle window — so a flaky LLM provider cannot quietly exhaust a session.
- **Thread state is not corrupted by mid-call failures.** The LangGraph checkpointer commits per-step, so an exception part-way through `generate_response` returns the thread to its last committed checkpoint. The next call resumes from that checkpoint.
- **No automatic retry inside the harness.** Retry policy is a consumer concern; the harness reports the failure verbatim. (When observability lands in Phase 4, the failure `reason` becomes a metric label.)
- **Recovery path**: the thread remains usable after a non-expiry failure. If the consumer wants a clean slate it calls `POST /api/v1/simulation/reset`. Expiry failures (`max_messages_exceeded`, `idle_timeout_exceeded`) are the only modes that auto-reset.
- **Queue-on-expiry — uniform error shape** ([REQUIREMENTS §1.7](./REQUIREMENTS.md#17-singleton-session-model)). When expiry fires, the in-flight call gets the expiry error and **every** call already in the FIFO queue MUST receive the **same** structured error (`max_messages_exceeded` or `idle_timeout_exceeded`) — not a generic "cancelled". Concretely: on the failing path inside `execute_tool`, before calling `_reset_thread()`, drain the waiter list and complete each waiter's future with the same `SessionExpiredError` instance. Only after the queue is empty does the thread reset. The next `tools/call` to arrive lands on the fresh thread normally. This keeps the consumer's retry/recovery branch identical for every member of a small batch.
- **Idle-timeout evaluation timing**. The idle check is run at the moment a queued call **acquires the lock**, against the timestamp of the last successful call — not at the moment the call entered the queue. A call that waits long enough in the queue can therefore fail with `idle_timeout_exceeded`, which then triggers the queue-drain rule above. This is also why the example `execute_tool` in §5.2 evaluates idle inside the `async with self._lock:` block, after the wait, not before.

Expiry payloads include the limit and the observed value so consumers can branch:

```json
{
  "isError": true,
  "reason": "max_messages_exceeded",
  "limit": 200,
  "observed": 200,
  "message": "max_messages exceeded; session reset"
}
```

```json
{
  "isError": true,
  "reason": "idle_timeout_exceeded",
  "limit_seconds": 1800,
  "observed_seconds": 1923.4,
  "message": "idle timeout exceeded; session reset"
}
```

#### 5.2.2 Concurrent Tool Calls — Bounded Queue

Per [REQUIREMENTS.md §1.7](./REQUIREMENTS.md#17-singleton-session-model), no two `tools/call` invocations execute against the agent at the same time. Phase 1 implements that as a **bounded FIFO queue** in front of the singleton thread, not pure rejection: a call arriving while another is in flight waits for the lock; a call arriving when the queue is full is rejected.

- **Queue depth**: configurable via `sessions.max_concurrent_queue_depth` in the YAML (§9). Default `8`. The depth counts in-flight + waiting; with default 8 that is one running call and up to seven waiters.
- **Overflow**: an arriving call that would push the queue past the cap is rejected immediately with an MCP `isError: true` result, `reason: "concurrent_queue_full"`. The counter and idle clock are not touched.
- **Wait timeout**: queued calls have no per-call wait timeout in Phase 1. The session-level idle timeout still governs the session as a whole, and the LLM call has its own provider-side timeout. Adding a wait-timeout knob is reserved for Phase 4 if it bites.
- **Ordering**: FIFO. Implementation uses an `asyncio.Semaphore(1)` plus an explicit waiter counter (the existing `asyncio.Lock` on `SimulationInstance` already gives us mutual exclusion; the counter is what enforces the cap).

The `queue_depth` field in `GET /api/v1/simulation` exposes the live waiter count for operator visibility.

### 5.3 Skill Registry — read-mostly in Phase 1

Per [REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative), runtime skill mutation is not in scope. The "registry" in Phase 1 is a thin wrapper around the on-disk `skills_folder` that handles two things at simulation creation: (a) check-then-reuse, and (b) one-shot generation when nothing's there.

```python
class SkillRegistry:
    """Read-mostly view over the on-disk skills folder (Phase 1)."""

    def __init__(self, skills_folder: Path, generator: SkillGenerator):
        self.skills_folder = skills_folder
        self.generator = generator

    def find_skill(self, name: str) -> Optional[Path]:
        """Return the skill folder if `<skills_folder>/<name>/SKILL.md` exists.

        Atomic-write guarantee (REQUIREMENTS §1.4): SKILL.md is only
        renamed into place after the skill has been fully generated, so
        this presence check cannot return a half-written skill.
        """
        candidate = self.skills_folder / name / "SKILL.md"
        return candidate.parent if candidate.is_file() else None

    async def ensure_skill(
        self,
        name: str,
        openapi_spec: dict,
        regenerate: bool = False,
    ) -> Path:
        """Reuse an existing skill or generate one. Returns the skill folder.

        openapi_spec is the inline JSON object passed in the create-simulation
        request (REQUIREMENTS §4.1) — not a URL or path.
        """
        existing = self.find_skill(name)
        if existing and not regenerate:
            return existing

        # Atomic write: generate into a temp dir under skills_folder, then
        # atomic-rename to <skills_folder>/<name>/. If generation fails
        # partway, the temp dir is cleaned up and no partial skill folder
        # is left behind. If <name>/ already exists (regenerate=true), it
        # is removed only after the temp dir is fully populated.
        return await self.generator.generate(
            name=name,
            openapi_spec=openapi_spec,
            output_dir=self.skills_folder,
        )
```

Skill *generation* (the LLM-powered process from `utils/skill-creator/skill_generator.py`) MAY be run as a **build-time / pre-deploy step** so the harness can reuse the on-disk skill at startup, OR triggered at simulation creation when no skill is present. Both paths use the same generator. Runtime *mutation* of an already-loaded skill (post-init add/regen) remains deferred to a later phase along with the §4.2 endpoints.

The adapted `SkillGenerator` (§6.4) does NOT carry its own YAML config — it takes the LLM client and generation knobs as constructor arguments built from the harness's main YAML. The upstream `utils/skill-creator/config.yaml` is dropped during the copy.

#### 5.3.1 Atomic-Write Failure Semantics

Atomic-rename only works within a single filesystem. The generator's temp directory MUST be a sibling of the target — i.e., `<skills_folder>/.<name>.tmp-<uuid>/` — never `/tmp/...`. Mounting `skills_folder` across an exotic FS boundary is the operator's problem; the design assumes one filesystem.

Concrete failure modes and harness behavior:

| Mode | Behavior |
|---|---|
| Temp-dir creation fails (disk full, permission denied) | `POST /api/v1/simulation` returns 5xx with the underlying OS error. No partial state. Host stays clean (`host.simulation = None`). |
| LLM generation raises mid-write | The partial temp dir is removed in a `finally` block. 5xx returned. No `<skills_folder>/<name>/` ever appears, so the reuse check cannot match a half-written skill. |
| Rename fails (cross-filesystem, permissions) | Temp dir cleaned up, 5xx returned. This shouldn't happen given the same-FS rule above; if it does, it indicates an operator misconfiguration of `skills_folder`. |
| `regenerate=true` and the existing folder removal fails after the new temp dir is fully populated | 5xx. The existing skill remains in place. Operator retries. |
| `regenerate=true`, succeeds: existing folder removed, new folder swapped in | The old skill is gone and not recoverable. Documented; operators are expected to keep their OpenAPI spec under version control if they care. |
| Concurrent `POST /api/v1/simulation` with `regenerate=true` targeting the same name | Cannot occur: `SimulationHost._lifecycle_lock` (§5.1) serializes all create paths. The second POST observes `simulation is not None` and gets 409. |

#### 5.3.2 Skill Reuse — Operator Footgun

Phase 1 deliberately does not fingerprint the OpenAPI spec against an existing skill ([REQUIREMENTS.md §1.4](./REQUIREMENTS.md#14-skill-generation-utility-integration)). To soften the footgun without paying for full fingerprinting:

- **At reuse time**, the harness MUST log a WARN at simulation creation: `"reusing existing skill <name> generated at <SKILL.md mtime>; OpenAPI spec is not fingerprinted. Pass regenerate: true if the spec has changed."`
- **Phase 3** roadmap: write `<skills_folder>/<name>/.spec.sha256` alongside `SKILL.md` at generation time. On reuse, compare the request spec's hash against the stored hash and log a structured WARN on mismatch. The harness still reuses the skill — "operator's responsibility" is preserved — but the operator gets an explicit signal instead of silent staleness.

### 5.4 Session Bookkeeping

There is no separate `SessionManager` in Phase 1. The singleton-session state — tool-call count, last-activity timestamp, the serializing lock — lives on `SimulationInstance` itself ([§5.2](#52-simulation-instance)). When (a) the multi-session model returns, (b) MCP-level session negotiation lands, or (c) a REST `/execute` path with caller-supplied `session_id` is reintroduced, this section becomes the home for a real `SessionManager`. Until then, keeping bookkeeping inside `SimulationInstance` avoids an extra abstraction over a single thread.

## 6. Code Reuse from mcp-simulation

### 6.1 Reuse Strategy — Copy and Adapt

The harness will be a **standalone project** that copies relevant components from `mcp-simulation` and adapts them.

**Why copy instead of import:**
- Independent evolution and maintenance.
- Simplified dependencies.
- Focused on simulation-harness specific needs.
- No coupling to `mcp-simulation` changes.

**Components to copy:**
1. **Deep Agent implementation** (`src/mcp_simulation/agent/deep_agent.py`) — LangChain Deep Agent integration, session management with LangGraph checkpointer, tool invocation handling.
2. **Skill generator** (`utils/skill-creator/skill_generator.py`) — LLM-powered skill generation from OpenAPI specs.
3. **OpenAPI parsing** (`src/mcp_simulation/openapi/`) — spec parsing, tool schema generation, schema validation.
4. **Configuration models** (`src/mcp_simulation/config/models.py`) — Pydantic configuration models, adapted to harness needs.
5. **Prompts** (`src/mcp_simulation/prompts/`) — system prompt templates and skill-based prompt templates.

**Components to rewrite:**
1. **MCP server** — new implementation that mounts on FastAPI with an SSE endpoint for any MCP-capable consumer.
2. **Simulator core** — simplified for simulation management only.
3. **Context management** — keep LangGraph checkpointer, simplify session handling.

### 6.2 File Mapping

```
mcp-simulation → simulation-harness

# Core Agent
src/mcp_simulation/agent/deep_agent.py
  → src/simulation_harness/agent/deep_agent.py

src/mcp_simulation/agent/session_manager.py
  → src/simulation_harness/agent/session_manager.py

src/mcp_simulation/agent/prompts.py
  → src/simulation_harness/agent/prompts.py

# Skill Generation
utils/skill-creator/skill_generator.py
  → src/simulation_harness/skills/generator.py

# OpenAPI Parsing
src/mcp_simulation/openapi/parser.py
  → src/simulation_harness/openapi/parser.py

src/mcp_simulation/openapi/tool_generator.py
  → src/simulation_harness/openapi/tool_generator.py

# Configuration (adapt)
src/mcp_simulation/config/models.py
  → src/simulation_harness/config/models.py

# Prompts
src/mcp_simulation/prompts/
  → src/simulation_harness/prompts/
```

### 6.3 Adaptation Process

**Step 1 — Copy core files:**
```bash
cp ../mcp-simulation/src/mcp_simulation/agent/deep_agent.py \
   src/simulation_harness/agent/

cp ../mcp-simulation/utils/skill-creator/skill_generator.py \
   src/simulation_harness/skills/generator.py

cp -r ../mcp-simulation/src/mcp_simulation/openapi/ \
   src/simulation_harness/openapi/

cp -r ../mcp-simulation/src/mcp_simulation/prompts/ \
   src/simulation_harness/prompts/
```

**Step 2 — Update imports:** replace all `from mcp_simulation.*` imports with `from simulation_harness.*`.

**Step 3 — Adapt configuration:**
- Remove visualization config (not needed).
- Add MCP server config (SSE endpoint).
- Add MCP server config (transport, mount paths).
- Keep LLM, agent, and OpenAPI configs.

**Step 4 — Simplify components:**
- Remove unused features (stdio transport, visualization).
  - Note: `mcp-simulation/src/mcp_simulation/core/simulator.py` imports `VisualizationLogger`, and several agent paths emit visualization events. Removing visualization is not just deleting `src/mcp_simulation/visualization/` — it requires sweeping the copied agent and core modules for `VisualizationLogger` calls and stripping them. Budget time accordingly.
- Focus on SSE/HTTP transport for MCP.
- Streamline session management.
- We are **not** vendoring an MCP implementation: depend on the official `mcp` SDK and integrate via the FastAPI mount pattern in §6.6.

### 6.4 Skill Generator — Adaptation

> **Superseded.** This section describes the original single-prompt generator, which loaded two packaged prompt assets (`generate_simulator_guide.md`, `skill_generator_prompt.md`) and asked one LLM call to emit `skill_md` + `schema_json` + `db_json` in one shot. It has been replaced by the multi-step pipeline in `skills/generation/` (`run_pipeline`), where each stage — analyze → operations → scenarios → schema → seed → assemble — carries its own prompt under `skills/assets/generation/`. The two monolithic assets were removed as orphaned; the description below is retained only as a record of the initial design.

The upstream `utils/skill-creator/skill_generator.py` reads a YAML config in `__init__` (`_load_config`) for: LLM model/temperature/max_tokens/api_key_env/base_api, the path to a generation guide markdown, the output directory, the `{api_name}-simulation` directory pattern, and a multi-page system prompt. We drop the YAML during the copy and split its contents into three buckets:

1. **LLM knobs** (`model`, `temperature`, `max_tokens`, `api_key_env`, `base_api`) — come from the harness's main YAML (§9) plus the optional `llm_config` override on `POST /api/v1/simulation`.
2. **Packaged assets** (`generation_guide` markdown, `system_prompt`) — copied into `src/simulation_harness/skills/assets/` and loaded by `importlib.resources` at module init. They are not configuration; they encode the skill-generator's behavior.
3. **Output knobs** (`skills_output_dir`, `skill_dir_pattern`) — replaced by direct arguments. The output directory is the harness's `skills_folder` and the skill directory name is the simulation `name` from the request, used verbatim (no template expansion).

Adapted constructor:

```python
class SkillGenerator:
    """Adapted from mcp-simulation/utils/skill-creator/skill_generator.py.

    No YAML; all knobs come in as arguments. Generation guide and
    system prompt are loaded from packaged assets at module import.
    """

    def __init__(
        self,
        llm_client,                       # pre-built provider client (harness-owned)
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 20000,
        verbose: bool = False,
        validate_output: bool = True,
    ):
        self.llm_client = llm_client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.verbose = verbose
        self.validate_output = validate_output
        # Packaged assets — frozen at module-build time.
        self._generation_guide = _load_asset("generate_simulator_guide.md")
        self._system_prompt = _load_asset("skill_generator_prompt.md")

    async def generate(
        self,
        name: str,                         # used verbatim as the skill folder name
        openapi_spec: dict,                # inline JSON object (REQUIREMENTS §4.1)
        output_dir: Path,                  # the harness's skills_folder
    ) -> Path:
        """Generate one skill under output_dir/<name>/ atomically.

        Writes into output_dir/<name>.tmp-<uuid>/ first, then renames to
        output_dir/<name>/ only after SKILL.md is fully written.
        Returns output_dir/<name>/.
        """
        ...
```

The harness instantiates `SkillGenerator` once at startup using the YAML's `llm.skill_generation_model` and the YAML's `llm.temperature`, and hands it to `SkillRegistry`. Per-simulation generation uses that single generator — no per-request reconfiguration in Phase 1.

> **Cross-check during copy**: confirm `utils/skill-creator/skill_generator.py`'s `generate_skill(...)` body so the adapted `generate(...)` produces the same prompt, validation, and output shape. The signature change is mechanical (drop `api_name_override` / template expansion, add atomic-write); the LLM-call logic stays.

### 6.5 Deep Agent Integration

The upstream agent (`mcp-simulation/src/mcp_simulation/agent/deep_agent.py`) exposes:

```python
class SimulatorAgent:
    def __init__(self, config: SimulatorConfig, spec: OpenAPISpec, operations: list[OpenAPIOperation]): ...
    async def generate_response(self, tool_name: str, arguments: dict, thread_id: str | None = None) -> Any: ...
    async def reset(self, thread_id: str | None = None) -> None: ...
    async def shutdown(self) -> None: ...
```

This is exactly what `SimulationInstance` (§5.2) calls. Two upstream details to keep in mind:

- The agent maps `thread_id=None` to `"default"` internally. The harness passes `_THREAD_ID = "default"` explicitly to be unambiguous.
- The agent has its own `SessionCleanupManager` configured by `config.agent.session_timeout_seconds` and `max_sessions`. With our singleton-thread model that internal manager would be racing the harness's own idle timeout. **Action during the copy**: set `session_timeout_seconds` to a value comfortably larger than the harness's `idle_timeout_seconds` (e.g., 10×) so the harness's fail-then-reset always fires first; alternatively, strip the cleanup manager from the copy. The simpler path is to leave it in but set it high.
- **LangGraph checkpointer**: Phase 1 inherits the `mcp-simulation` choice — LangGraph's in-memory `MemorySaver` (from `langgraph.checkpoint.memory`). It satisfies the §5.2.1 invariant that thread state is preserved at the last committed checkpoint across mid-call failures, has zero operational footprint, and is what the upstream agent already wires up. The PostgreSQL checkpointer in §7.3 is the production replacement. Picking a different in-memory implementation (e.g., a custom dict-backed saver) is **not** a Phase 1 task — copy what `mcp-simulation` uses verbatim.

`operations` is a `list[OpenAPIOperation]` produced by `OpenAPISpec.parse(...)` — `OpenAPISpec` parses the input and exposes `spec.operations` as the populated list. Construction flow inside `SimulationInstance.create(...)`:

```python
from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.agent.deep_agent import SimulatorAgent

@classmethod
async def create(cls, request_spec: SimulationSpec, harness_config: HarnessConfig) -> "SimulationInstance":
    # 1. Parse the inline OpenAPI JSON.
    # Validation depth (Phase 1):
    #   - Schema validation via openapi-spec-validator (already a dep). 3.0.x and 3.1.x both accepted.
    #   - Semantic validation: only what the validator already does (operationId uniqueness, $ref
    #     resolution). No custom Phase 1 checks beyond the validator.
    #   - Size limit: request body capped at 10 MB by FastAPI; oversize → 413 before parsing.
    #   - On failure: 422 with a structured error pointing to the failing path/keyword. No simulation
    #     created, no partial skill written (atomic-write rule, §5.3.1).
    spec = OpenAPISpec.parse(request_spec.openapi_spec)         # raises 4xx-mappable error on invalid spec
    operations = spec.operations                                # list[OpenAPIOperation]

    # 2. Resolve / generate the skill (atomic write, see §5.3 / §6.4).
    skill_dir = await skill_registry.ensure_skill(
        name=request_spec.name,
        openapi_spec=request_spec.openapi_spec,
        regenerate=request_spec.regenerate,
    )

    # 3. Build the agent's SimulatorConfig (fold harness YAML + per-request llm_config overrides).
    sim_config = build_simulator_config(harness_config, request_spec, skill_dir)

    # 4. Construct the agent.
    agent = SimulatorAgent(config=sim_config, spec=spec, operations=operations)

    # 5. Wrap with singleton-session bookkeeping (see §5.2).
    return cls(
        config=sim_config,
        agent=agent,
        max_messages=harness_config.sessions.max_messages,
        idle_timeout_seconds=harness_config.sessions.idle_timeout_seconds,
    )
```

If any step fails, no `SimulationInstance` is returned and `SimulationHost.create_simulation` propagates the error to the API (4xx for validation, 5xx for LLM/skill-gen failure). The lifecycle lock in §5.1 ensures a failed create leaves `host.simulation = None` so the next POST can retry.

#### 6.5.1 LLM Provider Abstraction (Phase 1 scope)

Provider differences (OpenAI function-calling vs. Anthropic tool use, etc.) are handled by LangChain's chat-model abstraction — the harness does not maintain a provider switch of its own. Phase 1 ships and is tested against OpenAI; other providers MAY work but are not validated.

- **Invalid model name**: caught at first LLM call. `SimulatorAgent.__init__` does not fully exercise the provider, so an invalid model is detected during the harness's synchronous initialization the moment the agent issues its first request, OR at the first `tools/call`. The harness propagates the provider's error verbatim — 4xx if the provider returns 4xx (e.g., model-not-found), 5xx for transport failures.
- **Provider-specific features** (function-calling vs. tool-use payload shapes) are LangChain's responsibility. If a future use case needs a feature LangChain doesn't abstract, that work goes into Phase 4 alongside the rest of the provider hardening.
- **Adding a new provider** in a later phase is mechanical: extend the YAML's `llm.provider` enum, wire the matching LangChain chat model, and re-run the acceptance tests. Phase 1 deliberately does not pre-build that switch.

### 6.6 MCP Server Integration Strategy

**Question**: Should we build on the official `mcp` Python SDK (the same one `mcp-simulation` uses) or implement MCP from scratch?

**Answer**: Use the official `mcp` SDK — copy `mcp-simulation`'s server code and integrate with FastAPI.

> Note: `mcp-simulation` does NOT use FastMCP (the higher-level convenience library). It uses the lower-level `mcp.server.*` APIs from the official SDK directly, and the harness does the same.
>
> **Why low-level `Server` and not FastMCP?** FastMCP's tool registration is decorator-first — it expects concrete annotated Python functions registered at import time. The harness needs the opposite: tools come from an OpenAPI spec parsed at simulation creation, with no Python signature, dispatched as `(name, dict_of_args) → response`. The low-level `Server` plus `list_tools` / `call_tool` handlers fits that dynamic-tools model directly. We still get the same wire protocol and the same mounting machinery (`StreamableHTTPSessionManager` is what FastMCP itself uses underneath); we just skip the decorator wrapper.

**Rationale:**
1. Proven implementation: `mcp-simulation`'s MCP server is battle-tested.
2. Multiple transports: supports SSE and streamable-http.
3. Side-by-side with FastAPI: can coexist with the FastAPI app.
4. Less work: don't reinvent the wheel.

**Integration approach:**

Phase 1 mounts **exactly one** transport against the shared `mcp.server.Server`, chosen at process startup by `mcp.transport` in the YAML ([REQUIREMENTS §1.3](./REQUIREMENTS.md#13-mcp-server-surface), §9):

- `mcp.transport: sse` → mount **SSE only** at `GET /mcp/sse` (with companion `POST /mcp/messages`) using `SseServerTransport`. Streamable-HTTP routes return 404.
- `mcp.transport: streamable_http` → mount **Streamable HTTP only** at `/mcp` (single ASGI mount) using `StreamableHTTPSessionManager` in `stateless=True` mode (no `Mcp-Session-Id` negotiation — statefulness lives in the agent thread, below MCP). SSE routes return 404.

There is no path-ordering caveat in Phase 1, because the two mounts are mutually exclusive. Phase 2 will lift this to dual-transport; **at that point** the SSE-routes-before-`/mcp`-mount ordering becomes load-bearing (a `Mount` at `/mcp` catches every `/mcp/*` request unless more-specific routes are registered first). The implementation below already keeps the SSE registration in a separate method that runs before the streamable-HTTP mount registration so the Phase 2 lift is mechanical — but Phase 1 only ever calls one of them.

```python
# src/simulation_harness/server/mcp_integration.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

class MCPIntegration:
    """Mount one mcp.server.Server on FastAPI under both transports."""

    def __init__(self, fastapi_app: FastAPI, mcp_server: Server):
        self.fastapi_app = fastapi_app
        self.mcp_server = mcp_server
        self._session_manager: StreamableHTTPSessionManager | None = None

    def mount_selected(self, transport: str) -> None:
        """Mount the configured transport (Phase 1: one or the other, never both).

        Phase 2 will replace this with mount_all() that mounts both. The Phase 1
        rule is: SSE registration must happen BEFORE streamable-HTTP mount
        registration when (eventually) both run, because the /mcp Mount would
        otherwise shadow /mcp/sse and /mcp/messages. The branches below preserve
        that intent so the Phase 2 lift is just deleting the elif.
        """
        if transport == "sse":
            self._mount_sse()
        elif transport == "streamable_http":
            self._mount_streamable_http()
        else:
            raise ValueError(f"unknown mcp.transport: {transport!r}")

    def _mount_sse(self) -> None:
        # SseServerTransport's argument is the post-message endpoint path.
        sse = SseServerTransport("/mcp/messages")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send,
            ) as streams:
                await self.mcp_server.run(
                    streams[0], streams[1],
                    self.mcp_server.create_initialization_options(),
                )

        async def handle_messages(request):
            await sse.handle_post_message(
                request.scope, request.receive, request._send,
            )

        self.fastapi_app.add_route("/mcp/sse", handle_sse, methods=["GET"])
        self.fastapi_app.add_route("/mcp/messages", handle_messages, methods=["POST"])

    def _mount_streamable_http(self) -> None:
        # stateless=True: no Mcp-Session-Id negotiation. Matches REQUIREMENTS §1.3
        # and the singleton-thread model in §5.2 — statefulness lives in the
        # agent thread, not the MCP transport.
        self._session_manager = StreamableHTTPSessionManager(
            app=self.mcp_server,
            event_store=None,
            json_response=True,
            stateless=True,
        )

        async def handle_http(scope, receive, send):
            await self._session_manager.handle_request(scope, receive, send)

        # Mount catches /mcp, /mcp/, and any /mcp/* path NOT already routed above.
        self.fastapi_app.mount("/mcp", handle_http)

    @asynccontextmanager
    async def lifespan(self):
        """FastAPI lifespan delegate. Drives the session manager's run loop."""
        if self._session_manager is None:
            yield
            return
        async with self._session_manager.run():
            yield
```

**Usage in main app:**

```python
# src/simulation_harness/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from simulation_harness.server.mcp_integration import MCPIntegration
from simulation_harness.server.mcp_server import MCPSimulatorServer

mcp_simulator = MCPSimulatorServer(config, spec, tool_handler)
mcp_integration = MCPIntegration(fastapi_app=None, mcp_server=mcp_simulator.server)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_integration.lifespan():
        yield

app = FastAPI(title="Simulation Harness", lifespan=lifespan)
mcp_integration.fastapi_app = app
mcp_integration.mount_selected(config.mcp.transport)  # "sse" or "streamable_http"

@app.post("/api/v1/simulation")
async def create_simulation(...):
    ...

# Result: single FastAPI app with:
# - REST management API at /api/v1/*
# - MCP (one of):
#     SSE              at GET /mcp/sse  + POST /mcp/messages
#     streamable HTTP  at /mcp          (single ASGI mount, stateless)
#   chosen at startup by config.mcp.transport. The other transport's routes 404.
```

**Benefits:**
- Single FastAPI application, single `mcp.server.Server` reachable through whichever transport the operator selected at startup.
- Both transport implementations live in the codebase from day one; the choice is a YAML knob, not a code-path divergence. Phase 2 promotes this to dual-transport without touching `MCPIntegration`'s internals.
- Coexists with the REST management API.
- Reuses the proven low-level MCP implementation from `mcp-simulation`.
- Streamable-HTTP plumbing uses the SDK's official `StreamableHTTPSessionManager` (the same machinery FastMCP uses) — no wheel-reinvention.

#### 6.6.1 Transport Parity Invariant (load-bearing)

Phase 1 only ever runs one transport per instance, but **both implementations** must be parity-equivalent so the YAML choice is a deployment knob, not a feature gate. The invariant: a consumer that switches `mcp.transport` from `sse` to `streamable_http` (or vice versa) and reconnects MUST observe identical behavior modulo wire format. Specifically:

- `tools/list` returns the same set of tools with the same schemas.
- `tools/call` produces the same result shape, including the structured error payloads in §5.2.1 (`max_messages_exceeded`, `idle_timeout_exceeded`, `concurrent_queue_full`, `llm_provider_error`, `tool_invocation_error`, `internal_error`).
- Session bookkeeping (counter increments, idle clock, expiry behavior, queue admission) is identical — both transports drive the same `SimulationInstance.execute_tool` path through the same `mcp.server.Server`, so this falls out of the architecture rather than being maintained by hand.
- Long-running tool calls behave identically: SSE streams the response over the open connection; Streamable HTTP returns it over the single request/response (configured via `json_response=True`). The wall-clock time is the same; the wire shape differs.
- Connection lifecycle is transport-specific (SSE keeps a long-lived connection; Streamable HTTP is request/response in stateless mode), but neither lifecycle leaks into tool semantics.

The only consumer-observable differences are wire format and connection lifecycle. **Any future change that breaks this invariant — different tools per transport, different error shapes, different counter behavior — is a design change, not an implementation detail.** This is why both transports share one `mcp.server.Server` and both flow through one `SimulationInstance`; the invariant is a property of the architecture, and reorganizing the mounting code must preserve it.

### 6.7 Dependencies

```toml
[project]
name = "simulation-harness"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",

    # LangChain/LangGraph (from copied code)
    "langchain>=0.1.0",
    "langchain-openai>=0.0.5",
    "langchain-core>=0.1.0",
    "langgraph>=0.0.20",
    "deepagents>=0.1,<0.2",  # LangChain Deep Agents — pre-1.0, pin tightly

    # OpenAPI parsing (from copied code)
    "openapi-spec-validator>=0.7.0",
    "jsonschema>=4.20.0",

    # MCP server — official Model Context Protocol SDK (NOT FastMCP)
    "mcp>=1.0.0",
    "starlette>=0.27.0",

    # Utilities
    "httpx>=0.26.0",
    "python-multipart>=0.0.6",
    "jinja2>=3.1.0",
    "pyyaml>=6.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
]
```

The harness depends on the official `mcp` SDK but NOT on the `mcp-simulation` package. The `mcp-simulation` server implementation is copied into this project per §6.1.

## 7. Extension Points for Future Iterations

### 7.1 Multi-Service Composition

**Current**: simulate one service per harness instance (one OpenAPI spec → one skill → one MCP server).
**Future**: simulate compositions of services (a "multi-service skill" that spans tools from several services).

```python
class MultiServiceSimulator:
    """Simulate a composition of services."""

    async def simulate(self, composition_definition: Dict, session_id: str) -> Any:
        # 1. Resolve the composition to a set of service simulations
        services = self._extract_service_dependencies(composition_definition)

        # 2. Ensure simulations exist for all services (one harness per service)
        for service in services:
            if not self.has_simulation(service):
                await self.create_service_simulation(service)

        # 3. Execute the composition against the simulated services
        return await self._execute_with_sims(composition_definition, session_id)
```

### 7.2 Authentication & Multi-Tenant Support

**Future**: reintroduce authentication (shared bearer token first, per-caller API keys later), and on top of that add tenant isolation, per-tenant resource quotas, and usage tracking. Phase 1 deliberately defers all of this ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)).

### 7.3 Persistent Storage

**Current**: in-memory checkpointer.
**Future**: PostgreSQL checkpointer for production.

```yaml
# In configuration
agent:
  checkpointer_type: "postgres"
  postgres_connection_string: "postgresql://..."
```

### 7.4 Observability

**Future**: structured JSON logs, Prometheus metrics (request rates/latencies, LLM token spend, active session counts), OpenTelemetry tracing. Phase 1 emits ordinary application logs only ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)). When this lands, metric names should use the prefix `simulation_harness_` so they can be scraped alongside any consumer platform's metrics.

### 7.5 Phase 1 Logging Floor

Per [REQUIREMENTS §2.4](./REQUIREMENTS.md#24-phase-1-logging-floor), Phase 1 emits one structured log line per `tools/call` so an operator can debug a failed Try without metrics infrastructure. The line is produced inside `SimulationInstance.execute_tool` (§5.2) on every exit path — success, expiry, queue overflow, LLM/tool/internal error — so coverage is uniform.

Concrete shape (key=value or JSON, pick one and stay consistent):

```
event=tools_call tool_name=searchFlights outcome=success duration_ms=2843
  tool_call_count=12 queue_depth_at_admission=0 transport=sse
  token_usage.prompt=412 token_usage.completion=98 token_usage.total=510
```

```
event=tools_call tool_name=bookFlight outcome=max_messages_exceeded
  duration_ms=3 tool_call_count=200 queue_depth_at_admission=1
  transport=sse token_usage=null
```

Field semantics:

- `outcome` is the same taxonomy as the MCP `reason` payload in §5.2.1, so a consumer-side error and an operator-side log line speak the same vocabulary.
- `tool_call_count` reports the **post-call** counter on success and the **pre-call** counter on every failure path (since failures don't advance the counter, §5.2.1). This keeps the value unambiguous: it is always "the counter the next call will see, plus zero or one depending on this call's outcome".
- `queue_depth_at_admission` is captured when the call enters the queue (before waiting on the lock), not at completion — the depth at completion is meaningless once you've drained.
- `token_usage` is `null` when no LLM call ran (queue overflow always; expiry when the limit is checked before the LLM is invoked, which is the case in the example `execute_tool` body).
- `transport` is constant for the life of the process (Phase 1 mounts one transport, §6.6); logged anyway so a single greppable line is self-contained.

Anything beyond this — aggregation, dashboards, alerts, span propagation — is Phase 4 work and MUST NOT block Phase 1.

## 8. Project Structure

```
simulation-harness/
├── src/
│   └── simulation_harness/
│       ├── __init__.py
│       ├── main.py                    # FastAPI app entry point
│       ├── config/
│       │   ├── __init__.py
│       │   ├── models.py              # Pydantic config models
│       │   └── settings.py            # Settings management
│       ├── api/
│       │   ├── __init__.py
│       │   ├── v1/
│       │   │   ├── __init__.py
│       │   │   └── simulations.py     # POST/GET/DELETE /simulation, /reset
│       │   │   # skills.py and execution.py — deferred past Phase 1
│       │   └── dependencies.py        # FastAPI dependencies
│       ├── core/
│       │   ├── __init__.py
│       │   ├── simulation_host.py     # SimulationHost (singleton holder)
│       │   ├── simulation_instance.py # SimulationInstance (owns singleton thread + counter + timer + lock)
│       │   └── skill_registry.py      # SkillRegistry (read-only in Phase 1)
│       │   # No session_manager.py in Phase 1 — see §5.4.
│       ├── models/
│       │   ├── __init__.py
│       │   ├── requests.py            # API request models
│       │   ├── responses.py           # API response models
│       │   └── domain.py              # Domain models
│       └── utils/
│           ├── __init__.py
│           ├── logging.py
│           └── errors.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── config/
│   └── harness.yaml                   # Default configuration
├── examples/
│   └── mcp-client/
│       └── example.py                 # Minimal MCP-capable consumer example
├── docs/
│   ├── USER_NEED.md
│   ├── REQUIREMENTS.md
│   ├── DESIGN.md
│   └── ALPHA_USE_CASE.md
├── pyproject.toml
├── README.md
└── Makefile
```

## 9. Configuration

The harness is configured by a single YAML file ([REQUIREMENTS.md §1.6](./REQUIREMENTS.md#16-configuration-file)). Defaults defined here are the source of truth: the management API may override `skills_folder` and `llm_config` per simulation, but if it doesn't, these values apply. The harness refuses to start if the config is missing, unparseable, or invalid.

API keys may be given either as a literal value (`api_key`) or as the name of an environment variable to read from (`api_key_env`). At least one form must resolve to a non-empty string for the configured provider.

```yaml
# config/harness.yaml

server:
  host: "0.0.0.0"
  port: 8000

# MCP transport selection (REQUIREMENTS §1.3). One of `sse` or `streamable_http`.
# Phase 1 mounts exactly one transport per instance — the other's routes 404.
# No default: the operator MUST choose. Phase 2 will lift this to dual-transport.
mcp:
  transport: "sse"   # or "streamable_http"

# LLM configuration. `simulation_model` is used by the deep agent at runtime
# (model + temperature are overridable per-simulation via the API).
# `skill_generation_model` is used by the skill-generation utility.
# `provider` is fixed at process startup and cannot be overridden per
# simulation (REQUIREMENTS §1.6).
llm:
  provider: "openai"
  simulation_model: "gpt-4o-mini"
  skill_generation_model: "gpt-4o"

  # Default sampling temperature for both skill-generation and the simulation
  # deep agent. Phase 1 default is 0 (deterministic). The runtime API may
  # override this for the simulation model only; skill-generation temperature
  # is sourced exclusively from this YAML.
  temperature: 0

  # Provide ONE of api_key or api_key_env (the harness accepts both).
  api_key_env: "OPENAI_API_KEY"
  # api_key: "sk-..."

  # Optional override for the LLM provider's base URL. Use for self-hosted
  # deployments, gateways, or OpenAI-compatible providers. Omit to use the
  # SDK default. Accepts either a literal `api_base` or an `api_base_env`
  # naming an env var to read from.
  # api_base: "https://my-gateway.internal/v1"
  # api_base_env: "OPENAI_API_BASE"

# Skill folder: the agent loads skills from here at simulation creation,
# and the skill-generation utility writes new skills here.
skills:
  folder: "./skills"

# Singleton-session limits (REQUIREMENTS §1.7). One implicit session per
# harness instance; both limits trigger fail-then-reset.
sessions:
  # Maximum number of MCP `tools/call` invocations against the singleton
  # thread before it is considered expired. Phase 1 counts tool calls, not
  # tokens or LangGraph state messages — simpler and provider-independent.
  max_messages: 200
  # Idle timeout in seconds. If no tool call has landed in this many seconds
  # since the last one, the session is considered expired. The clock starts
  # at the first call after creation/reset (not at simulation creation).
  idle_timeout_seconds: 1800
  # Bounded queue in front of the singleton thread (§5.2.2). Counts in-flight
  # + waiting `tools/call` invocations. Default 8 = one running, up to seven
  # waiters. An arriving call that would push past this cap is rejected with
  # an MCP isError result (reason: "concurrent_queue_full").
  max_concurrent_queue_depth: 8

logging:
  level: "INFO"
```

Phase 1 deliberately leaves out auth, metrics, and tracing config blocks — those will reappear when [§7.2](#72-authentication--multi-tenant-support) and [§7.4](#74-observability) are picked up.

#### 9.1 Configuration Lifecycle

The YAML is read **once at process startup**. There is no hot-reload in Phase 1 — changes (LLM credentials, models, session limits, skill folder, queue depth) require a process restart. In-flight simulations terminate when the process exits; the in-memory checkpointer means the singleton thread is not persisted, so the next process starts with no simulation until `POST /api/v1/simulation` is called again.

Operators relying on rolling restarts to pick up config changes should plan for one simulation's worth of state loss per restart. Hot-reload is on the Phase 4 roadmap alongside observability ([§7.4](#74-observability)); reload of safe knobs (logging level, session limits) is the natural first step, and reload of LLM credentials / provider is the harder case because credentials are bound to the agent at construction time.

#### 9.2 Skill Folder — Filesystem Requirements

- The harness needs **read+write** on `skills_folder` at startup. Writes happen during skill generation (atomic temp dir + rename, §5.3.1); reads happen at every simulation creation that reuses an existing skill.
- The temp directory used for atomic generation MUST be a sibling of the target skill folder (under `skills_folder` itself), so atomic-rename stays within one filesystem.
- If `skills_folder` becomes read-only after startup, generation requests fail with 5xx; the reuse path still works.
- **Multi-instance shared folders are out of scope for Phase 1.** Each harness instance owns its own `skills_folder`. A shared read-only "skill cache" pattern across instances is on the Phase 4 roadmap alongside auth and multi-tenant ([§7.2](#72-authentication--multi-tenant-support)); without it, two instances writing to the same folder concurrently are not protected by `SimulationHost._lifecycle_lock` (which is per-process) and may race during atomic rename.

## 10. Deployment

### 10.1 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install -e .

COPY src/ ./src/
COPY config/ ./config/

EXPOSE 8000 9090

CMD ["uvicorn", "simulation_harness.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10.2 Kubernetes

> One simulation per pod. Use one Deployment per simulated service (e.g., `harness-flight-booking`, `harness-payments`). `replicas` here is purely for HA of a single simulation, not for hosting multiple simulations on one Deployment. Cross-simulation orchestration belongs to whatever system manages these Deployments.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: harness-flight-booking
spec:
  replicas: 1  # raise for HA; each replica still hosts the same one simulation
  selector:
    matchLabels:
      app: harness-flight-booking
  template:
    metadata:
      labels:
        app: harness-flight-booking
    spec:
      containers:
      - name: harness
        image: simulation-harness:latest
        ports:
        - containerPort: 8000
        env:
        # The harness reads its YAML config (mounted at /etc/harness/harness.yaml).
        # The YAML's `api_key_env: OPENAI_API_KEY` resolves against this env var.
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: llm-secrets
              key: openai-api-key
        volumeMounts:
        - name: harness-config
          mountPath: /etc/harness
          readOnly: true
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
      volumes:
      - name: harness-config
        configMap:
          name: harness-flight-booking-config
```

Phase 1 pods are unauthenticated; expose them only on cluster-internal addresses until §7.2 lands.

## 11. Development Roadmap

### Phase 1 — Foundation + Service-Level Simulation (current)

Scope-shaped by [REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative): single simulation per instance (one OpenAPI spec → one skill → one MCP server), no `/chat`, no runtime skill mutation, dynamic registration via management API, YAML-driven configuration, security/scalability/observability deferred. The alpha consumer integration is described in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md).

- [x] Design document
- [ ] Project scaffolding
- [ ] YAML config loader with validation; refuse to start on missing/invalid config
- [ ] FastAPI server with `POST/GET/DELETE /api/v1/simulation` and `POST /api/v1/simulation/reset` (no `/execute`, no `/sessions/{id}` in Phase 1)
- [ ] Copy & adapt deep agent + OpenAPI parsing + prompts from `mcp-simulation`
- [ ] MCP server mounted on FastAPI under **exactly one** transport per instance (chosen at startup by `mcp.transport` in the YAML) via the official `mcp` SDK: SSE at `/mcp/sse` + `/mcp/messages` (`SseServerTransport`) **or** streamable-HTTP at `/mcp` (`StreamableHTTPSessionManager`, `stateless=True`). Both implementations live in the codebase; the non-selected one's routes return 404. Phase 2 will lift this to dual-transport.
- [ ] Skills loaded once at simulation creation from the configured skill folder
- [ ] Skill reuse-or-generate at simulation creation: reuse `<skills_folder>/<name>/SKILL.md` if present; regenerate only when the request sets `regenerate: true`
- [ ] Atomic skill-folder writes: generate into a temp dir under `skills_folder`, rename to `<name>/` only on success — partial generation never leaves a discoverable skill behind
- [ ] Adapt `SkillGenerator` to drop its YAML: take LLM knobs as constructor args, load generation guide and system prompt from packaged assets
- [ ] OpenAPI spec accepted as inline JSON object on `POST /api/v1/simulation`; URL/path/upload deferred
- [ ] Lifecycle lock on `SimulationHost` so concurrent `POST /simulation` (and DELETE+POST races) cannot leave the host half-initialized
- [ ] Reject per-simulation `provider` overrides; only `model` and `temperature` are overridable
- [ ] Singleton-session bookkeeping in `SimulationInstance`: tool-call counter, idle timer (clock starts at first call), serializing `asyncio.Lock`, and a bounded waiter counter for `sessions.max_concurrent_queue_depth` (§5.2.2)
- [ ] Limit enforcement: tool call exceeding `max_messages` or `idle_timeout_seconds` returns an MCP `isError: true` result with a structured `{ reason, limit, observed }` payload (§5.2.1) and resets the thread; subsequent call starts fresh
- [ ] Concurrent queue overflow returns an MCP `isError: true` result with `reason: "concurrent_queue_full"`; counter and idle clock are not touched
- [ ] LLM-provider and tool-invocation failures surface as MCP `isError: true` with `reason: "llm_provider_error"` / `"tool_invocation_error"`; counter and idle clock unchanged; thread state preserved at last LangGraph checkpoint (§5.2.1)
- [ ] On skill reuse at simulation creation, log a WARN naming the skill, its `SKILL.md` mtime, and reminding the operator to pass `regenerate: true` if the spec has changed (§5.3.2)
- [ ] OpenAPI spec validated via `openapi-spec-validator` (3.0.x and 3.1.x); request body capped at 10 MB; failures return 422 with a structured error
- [ ] `GET /api/v1/simulation` exposes the singleton-session block: `tool_call_count`, `max_messages`, `seconds_since_last_call`, `idle_timeout_seconds`, `queue_depth`, `max_concurrent_queue_depth`
- [ ] `POST /api/v1/simulation/reset` resets the thread, counter, and idle timer
- [ ] End-to-end test: register simulation → list tools via MCP → make multiple `tools/call` invocations against one MCP session that share context → verify reset clears it
- [ ] End-to-end transport-parity test: identical sequence of `tools/list` + `tools/call` produces identical tool sets, identical result shapes, and identical session bookkeeping side-effects across two harness processes — one started with `mcp.transport: sse`, one with `mcp.transport: streamable_http` (§6.6.1)
- [ ] Queue-on-expiry uniform-error-shape test: with several queued `tools/call`s in flight, force expiry on the running call and assert every queued call resolves with the same `reason` (`max_messages_exceeded` or `idle_timeout_exceeded`) — not a generic cancellation — before the next call lands on a fresh thread (§5.2.1)
- [ ] Idle-timeout-on-queue-wait test: a call that waits long enough for the lock that the configured idle window elapses MUST fail with `idle_timeout_exceeded` (evaluated at lock acquisition, not at queue entry); the queue-drain rule applies (§5.2.1)
- [ ] Per-`tools/call` structured log line emitted on every exit path (success, expiry, queue-overflow, LLM/tool/internal error) with fields: `tool_name`, `outcome`, `duration_ms`, `tool_call_count`, `queue_depth_at_admission`, `transport`, `token_usage` (§7.5)
- [ ] Single management-API error envelope `{ error: { code, message, details? } }` used by every 4xx/5xx response from `POST/GET/DELETE /api/v1/simulation` and `POST /api/v1/simulation/reset`, with the `code` taxonomy in §4.0
- [ ] LangGraph checkpointer is `MemorySaver` from `langgraph.checkpoint.memory`, matching `mcp-simulation`'s choice (§6.5)

### Phase 2 — Multi-Service Composition

- [ ] Resolve a multi-service skill (ordered set of service identifiers) to a set of harness instances / MCP URLs
- [ ] Multi-tool sessions with shared context across services
- [ ] Validation against at least one real consumer integration

### Phase 3 — Runtime Skill Mutation & Conversational Surface

- [ ] `POST /api/v1/simulation/skills` — runtime skill add/regen
- [ ] `POST /api/v1/simulation/chat` — conversational endpoint
- [ ] Hot-reload mechanism (or accept session loss on agent recreate)

### Phase 4 — Production Readiness

- [ ] Authentication (shared bearer token, then per-caller API keys)
- [ ] Observability — structured logs, Prometheus metrics, OpenTelemetry tracing, token-spend telemetry
- [ ] Scalability target — concurrent-session SLO, latency SLO once telemetry exists
- [ ] PostgreSQL checkpointer
- [ ] Multi-tenant support
- [ ] Rate limiting / cost caps
- [ ] Documentation

## 12. Open Questions

Resolved (kept here for traceability):

- ~~**Consumer-specific skill formats**~~ — *Resolved.* The harness does not consume any consumer's skill schema; consumers resolve their own skill definitions to a set of MCP URLs + tool names and call the harness through the standard MCP path. No format converter needed in the harness.
- ~~**Multi-simulation routing**~~ — *Resolved*: one simulation per harness instance.
- ~~**Granularity**~~ — *Resolved*: service-level (one OpenAPI spec → one skill → one simulation per instance).
- ~~**`/chat` endpoint**~~ — *Resolved*: deferred to Phase 3.
- ~~**Runtime skill mutation**~~ — *Resolved*: deferred to Phase 3.
- ~~**Simulation lifecycle**~~ — *Resolved*: dynamic registration via `POST /api/v1/simulation`.
- ~~**Authentication**~~ — *Resolved*: deferred to Phase 4. Phase 1 endpoints are unauthenticated; rely on network isolation.
- ~~**Default LLM model**~~ — *Resolved*: defaults come from the YAML config; the API may override per-simulation.
- ~~**Configuration source**~~ — *Resolved*: single YAML file (§9).
- ~~**Latency SLO**~~ — *Resolved*: no Phase 1 SLO.
- ~~**Scalability target**~~ — *Resolved*: deferred to Phase 4.
- ~~**Observability**~~ — *Resolved*: deferred to Phase 4. Phase 1 emits ordinary application logs only.
- ~~**Rate limiting / cost caps**~~ — *Resolved*: deferred to a later phase.

Still open:

1. **Skill versioning**: how is a skills-folder change reflected when the simulation already exists? Phase 1 answer is "DELETE then POST again" plus the reuse-WARN log (§5.3.2); the spec-fingerprint comparison goes into Phase 3 alongside runtime skill mutation.
2. **Skill sharing / privacy**: with single-simulation-per-instance the natural model is one instance = one tenant. Revisit if multi-tenant-per-instance is ever needed (Phase 4).
3. **Configuration hot-reload**: Phase 1 requires a process restart for any config change (§9.1). Phase 4 may add reload for safe knobs (logging level, session limits, queue depth); reload of LLM credentials / provider is harder and may stay a restart-only path.

Resolved (kept here for traceability):

- ~~**Tool-execution surface**~~ — *Resolved*: MCP `tools/call` only in Phase 1. `/execute` and `/chat` deferred. (See [§3](#3-consumer-integration-pattern), [§4.3](#43-tool-execution--deferred-at-the-rest-layer-post-phase-1).)
- ~~**Session model**~~ — *Resolved*: one implicit stateful thread per harness instance, expired by tool-call cap, idle timeout, or explicit `/reset`. Fail-then-reset on limit breach. Calls serialized with an `asyncio.Lock`. ([§5.2](#52-simulation-instance), [REQUIREMENTS §1.7](./REQUIREMENTS.md#17-singleton-session-model).)
- ~~**Session-length unit**~~ — *Resolved*: tool-call count, not tokens or LangGraph state messages. Simpler and provider-independent; tokens can come back as an option in a later phase.
- ~~**Idle-timer clock**~~ — *Resolved*: starts at the first tool call after creation or reset (not at simulation creation), so a quiet simulation does not expire before its first use.
- ~~**Concurrent calls**~~ — *Resolved for Phase 1*: serialized via lock; one harness instance = single-tenant. Multi-session and overlap policy revisit when [§7.2](#72-authentication--multi-tenant-support) lands.
- ~~**Skill-generator config**~~ — *Resolved*: drop the upstream `utils/skill-creator/config.yaml` entirely during the copy. LLM knobs come from the harness YAML + per-request overrides; generation guide and system prompt are packaged assets. ([§6.4](#64-skill-generator--adaptation).)
- ~~**OpenAPI input shape**~~ — *Resolved*: inline JSON object only in Phase 1. URL fetch, multipart upload, and local path are deferred. ([REQUIREMENTS §4.1](./REQUIREMENTS.md#41-openapi-spec-input-shape).)
- ~~**Streamable-HTTP transport**~~ — *Resolved*: included in Phase 1, mounted alongside SSE under one shared `mcp.server.Server`. SSE at `/mcp/sse` + `/mcp/messages`; streamable-HTTP at `/mcp` (stateless). Implemented via the SDK's `SseServerTransport` and `StreamableHTTPSessionManager` — same machinery FastMCP uses, without taking on FastMCP's decorator-based tool model. ([§6.6](#66-mcp-server-integration-strategy).)
- ~~**FastMCP vs low-level `Server`**~~ — *Resolved*: low-level `Server`. FastMCP's tool registration is decorator-first and assumes annotated Python functions registered at import time, which is incompatible with the harness's dynamic OpenAPI-driven tool model. We keep the same SDK mounting machinery (no reinvention) but skip the decorator wrapper. ([§6.6](#66-mcp-server-integration-strategy).)
- ~~**Per-simulation provider override**~~ — *Resolved*: provider is locked at process startup; the API may override `model` and `temperature` only. ([§4.1](#41-management-api), [REQUIREMENTS §1.6](./REQUIREMENTS.md#16-configuration-file).)
- ~~**Default temperature**~~ — *Resolved*: 0, set in the YAML's `llm.temperature`. Overridable per-simulation for the simulation model; skill-generation temperature is YAML-only. ([§9](#9-configuration).)
- ~~**Concurrent `POST /simulation`**~~ — *Resolved*: `SimulationHost._lifecycle_lock` serializes create/delete; second concurrent POST receives 409. ([§5.1](#51-simulation-host).)
- ~~**Partial skill-generation cleanup**~~ — *Resolved*: atomic write — generate into a temp dir, rename to `<name>/` only on success. The reuse check (`SKILL.md` presence) cannot match a half-written skill. ([§5.3](#53-skill-registry--read-mostly-in-phase-1), [REQUIREMENTS §1.4](./REQUIREMENTS.md#14-skill-generation-utility-integration).)
- ~~**Upstream agent signature**~~ — *Resolved*: `SimulatorAgent.__init__(config, spec, operations)`, `generate_response(tool_name, arguments, thread_id)`, `reset(thread_id)`, `shutdown()`. `operations` comes from `OpenAPISpec.parse(...).operations`. ([§6.5](#65-deep-agent-integration).)
- ~~**`tools/call` failure semantics**~~ — *Resolved*: three failure classes (session expiry, queue overflow, internal/LLM/tool error) all surface as MCP `isError: true` with a structured `{ reason, ... }` payload. Counter and idle clock advance only on success; thread state preserved at the last LangGraph checkpoint on non-expiry failures; no automatic retry. ([§5.2.1](#521-failure-semantics-for-toolscall).)
- ~~**Concurrent tool calls — queue vs reject**~~ — *Resolved*: bounded FIFO queue, configurable depth (`sessions.max_concurrent_queue_depth`, default 8), overflow returns MCP `isError: true` with `reason: "concurrent_queue_full"`. ([§5.2.2](#522-concurrent-tool-calls--bounded-queue).)
- ~~**Session expiry UX**~~ — *Resolved*: structured MCP error with `reason`, `limit`, `observed`; live counters exposed via `GET /api/v1/simulation` for proactive consumer management. ([§4.1](#41-management-api), [§5.2.1](#521-failure-semantics-for-toolscall).)
- ~~**OpenAPI validation depth**~~ — *Resolved*: schema validation via `openapi-spec-validator` (accepts 3.0.x and 3.1.x); semantic checks limited to what the validator already does; 10 MB body cap; failures return 422 with structured error. ([§6.5](#65-deep-agent-integration).)
- ~~**Skill reuse footgun**~~ — *Resolved*: WARN logged at every reuse naming the skill and its `SKILL.md` mtime. Spec fingerprinting (`<skills_folder>/<name>/.spec.sha256`) deferred to Phase 3. ([§5.3.2](#532-skill-reuse--operator-footgun).)
- ~~**Atomic-write edge cases**~~ — *Resolved*: temp dir is a sibling of the target under `skills_folder` (same FS guarantee); explicit failure mappings for disk-full, permission, mid-write, rename-fail, and `regenerate=true` swap-fail. Concurrent same-name `regenerate=true` cannot occur — `_lifecycle_lock` serializes create paths. ([§5.3.1](#531-atomic-write-failure-semantics).)
- ~~**Transport parity invariant**~~ — *Resolved*: SSE and Streamable HTTP are identical from the consumer's perspective modulo wire format and connection lifecycle; tool sets, result shapes, error payloads, counter/idle behavior, and queue admission all flow through one `mcp.server.Server` and one `SimulationInstance`. ([§6.6.1](#661-transport-parity-invariant-load-bearing).)
- ~~**Configuration lifecycle**~~ — *Resolved*: read once at process startup; changes require restart. Hot-reload deferred to Phase 4. ([§9.1](#91-configuration-lifecycle).)
- ~~**Skill folder permissions / multi-instance**~~ — *Resolved*: read+write at startup; sibling-temp-dir for atomic rename; multi-instance shared folders out of scope for Phase 1. ([§9.2](#92-skill-folder--filesystem-requirements).)
- ~~**LLM provider abstraction**~~ — *Resolved*: LangChain handles provider differences; Phase 1 tested against OpenAI; invalid model names propagate the provider's error verbatim. ([§6.5.1](#651-llm-provider-abstraction-phase-1-scope).)
- ~~**Cross-transport concurrency model**~~ — *Resolved*: Phase 1 mounts exactly one transport per instance, chosen at startup via `mcp.transport`. No runtime first-wins, no inter-transport lock. Dual-transport is Phase 2. ([§6.6](#66-mcp-server-integration-strategy), [REQUIREMENTS §1.3](./REQUIREMENTS.md#13-mcp-server-surface).)
- ~~**Queue-on-expiry behavior**~~ — *Resolved*: queued calls die with the session and receive the same structured expiry error as the in-flight call (`max_messages_exceeded` / `idle_timeout_exceeded`), not a generic cancellation. Idle is evaluated at lock-acquisition time, not at queue entry. ([§5.2.1](#521-failure-semantics-for-toolscall), [REQUIREMENTS §1.7](./REQUIREMENTS.md#17-singleton-session-model).)
- ~~**Management-API error envelope**~~ — *Resolved*: single shape `{ error: { code, message, details? } }` with a fixed Phase 1 code taxonomy. MCP `tools/call` failures keep their separate `isError: true` envelope. ([§4.0](#40-error-envelope-single-shape-across-the-management-api).)
- ~~**Phase 1 logging floor**~~ — *Resolved*: one structured log line per `tools/call` on every exit path, with `tool_name` / `outcome` / `duration_ms` / `tool_call_count` / `queue_depth_at_admission` / `transport` / `token_usage`. Anything richer is Phase 4. ([§7.5](#75-phase-1-logging-floor), [REQUIREMENTS §2.4](./REQUIREMENTS.md#24-phase-1-logging-floor).)
- ~~**LangGraph checkpointer choice**~~ — *Resolved*: `MemorySaver` from `langgraph.checkpoint.memory`, matching `mcp-simulation`. PostgreSQL checkpointer is the production replacement (§7.3). ([§6.5](#65-deep-agent-integration).)

---

**Document Version**: 3.2
**Last Updated**: 2026-05-30
**Author**: Bob (AI Assistant)
**Status**: Draft — awaiting review
