# Simulation Harness — Alpha Use Case

This document describes the concrete alpha integration: **Skillberry Store's "Try" button, backed by the Simulation Harness as an MCP backend**. It is one specific instance of the broader use cases described in [USER_NEED.md](./USER_NEED.md) — namely, **Use Case 1 (Catalog Exploration / "Try")** with **Skillberry Store** as the consumer platform. It grounds the platform-agnostic design ([DESIGN.md](./DESIGN.md)) in a real integration and is the scenario against which the Phase 1 acceptance criteria ([REQUIREMENTS.md §6](./REQUIREMENTS.md#6-acceptance-criteria-phase-1)) are evaluated.

> **Scope of this document.** All Skillberry-specific content lives here. The harness itself ([REQUIREMENTS.md](./REQUIREMENTS.md), [DESIGN.md](./DESIGN.md)) is platform-agnostic — Skillberry is just the first consumer. Future per-consumer documents (e.g., for an optimization mechanism using Use Case 2, or an agentic platform integrating Use Case 3) will follow this same shape.

## 1. Alpha Personae & Goal

This alpha integration realizes the personae from [USER_NEED.md §2](./USER_NEED.md#2-personae) in the Skillberry Store environment:

- **Agent developer** = a Skillberry Store user browsing the tool/skill catalog.
- **DevOps engineer** = the operator running the Skillberry Store deployment, who is also responsible for deploying and configuring the harness instances Skillberry routes to.

**Goal**: an agent developer clicks **Try** on a tool in the Skillberry catalog, supplies arguments, and gets a realistic mock response — with no real backend, no credentials, and no setup beyond what the DevOps engineer did once at deploy time.

The user-facing motivation is in [USER_NEED.md](./USER_NEED.md). This document focuses on the concrete plumbing for the Skillberry Store consumer.

## 2. Skillberry Store — Relevant Capabilities

Skillberry Store is a FastAPI-based service for managing tools, skills, and snippets. The pieces relevant to this integration:

- **Tool execution**: tools are executed in Docker sandboxes with parameter validation.
- **MCP backend support**: tools with `packaging_format=mcp` are dispatched to an MCP backend specified by `packaging_params.mcp_url` and `packaging_params.mcp_tool_name`.
- **Schemas**:
  ```python
  class ToolSchema(ManifestSchema):
      module_name: Optional[str]
      programming_language: str = "python"
      packaging_format: str  # "code" or "mcp"
      packaging_params: Optional[Dict]  # For MCP: {mcp_url, mcp_tool_name}
      # ... parameters, returns, dependencies

  class SkillSchema(ManifestSchema):
      tool_uuids: List[str]      # Ordered list of tool UUIDs
      snippet_uuids: List[str]   # Ordered list of snippet UUIDs
  ```
- **Dispatch**: `skillberry-store/src/skillberry_store/schemas/tool_schema.py` and `modules/file_executor.py` route `packaging_format=mcp` calls through the MCP URL/tool-name pair.

The harness only needs to expose MCP tools; Skillberry wraps them in `ToolSchema` itself. The harness never produces or consumes `ToolSchema` directly.

## 3. End-to-End Alpha Flow

### 3.1 Setup (one-time per simulated service)

The operator (or a Skillberry admin / automation script) wires up a new simulated service exactly once. Skillberry registers each of the service's tools in its catalog, all pointing at the same harness MCP URL but with different `mcp_tool_name` values:

```
Operator deploys a harness pod (one per simulation, per REQUIREMENTS §4)
         ↓
Operator (or automation) calls POST /api/v1/simulation with the OpenAPI spec
         ↓
Harness parses spec, initializes agent, MCP endpoint /mcp/sse goes live
         ↓
A Skillberry tool is registered with:
  packaging_format = "mcp"
  packaging_params = {
    "mcp_url":       "http://harness-<sim>:8000/mcp/sse",
    "mcp_tool_name": "searchFlights"
  }
```

`POST /api/v1/simulation` is synchronous — by the time it returns 200, MCP `tools/list` returns the parsed tools and the endpoint is ready to serve calls.

### 3.2 Per-call (each user click)

```
User clicks "Try" on a tool in Skillberry Store UI
         ↓
Skillberry's file_executor opens an SSE session to the harness, lists tools,
and calls searchFlights with the user-supplied arguments
         ↓
Harness deep agent generates a simulated response
         ↓
Skillberry returns the response to the UI; user sees realistic mock data
```

### 3.3 "Try" Button Flow Diagram

```
┌──────────────────┐
│ Skillberry Store │
│      UI          │
└────────┬─────────┘
         │ 1. User clicks "Try" on flight-booking tool
         ▼
┌─────────────────────────────────────────────────┐
│ Skillberry Store Backend                        │
│ Tool registered earlier as:                     │
│ {                                               │
│   "name": "searchFlights",                      │
│   "packaging_format": "mcp",                    │
│   "packaging_params": {                         │
│     "mcp_url": "http://harness:8000/mcp/sse",   │
│     "mcp_tool_name": "searchFlights"            │
│   }                                             │
│ }                                               │
└────────┬────────────────────────────────────────┘
         │ 2. User executes tool via Skillberry UI
         │    POST /tools/{uuid}/execute
         │    { "origin": "JFK", "destination": "LAX" }
         ▼
┌─────────────────────────────────────────────────┐
│ Skillberry routes to MCP backend (harness)      │
└────────┬────────────────────────────────────────┘
         │ 3. MCP tools/call over SSE
         ▼
┌─────────────────────────────────────────────────┐
│ Simulation Harness (MCP Server)                 │
│ Tool: searchFlights                             │
│ Arguments: {origin: "JFK", destination: "LAX"}  │
└────────┬────────────────────────────────────────┘
         │ 4. Harness generates mock response
         ▼
┌─────────────────────────────────────────────────┐
│ Response: {                                     │
│   "flights": [                                  │
│     {"flight": "AA123", "price": 299.99, ...}   │
│   ]                                             │
│ }                                               │
└────────┬────────────────────────────────────────┘
         │ 5. User sees realistic simulation
         ▼
┌──────────────────┐
│ Skillberry Store │
│   UI displays    │
│   mock results   │
└──────────────────┘
```

## 4. Harness MCP Surface (What Skillberry Sees)

The harness exposes an MCP-compatible surface for the simulated service over two transports backed by one shared `mcp.server.Server` ([DESIGN §6.6](./DESIGN.md#66-mcp-server-integration-strategy)):

- **SSE**: `GET /mcp/sse` (with companion `POST /mcp/messages`) — Skillberry's current `mcp_url` shape points at the `/mcp/sse` URL.
- **Streamable HTTP**: `/mcp` — single ASGI mount, stateless mode. Available for any consumer whose MCP client speaks streamable-HTTP rather than SSE.
- **Tool discovery**: on connect, the harness exposes the service's tools via the MCP `tools/list` method (identical results across both transports).
- **Tool execution**: consumers invoke tools via the MCP `tools/call` method (identical handling across both transports; both share the singleton agent thread).

Phase 1 endpoints are unauthenticated ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)) — the alpha relies on cluster-internal network isolation. Authentication will be reintroduced in a later phase.

## 5. Lifecycle Recap

The Phase 1 model — **dynamic registration via management API + one simulation per harness instance** ([REQUIREMENTS.md §4](./REQUIREMENTS.md#4-phase-1-scope-decisions-authoritative)) — produces this lifecycle in the Skillberry deployment:

1. **Deploy a harness instance** (one Kubernetes pod per tool/skill being simulated). MCP endpoint `/mcp/sse` is mounted but `tools/list` is empty until step 2.
2. **Skillberry (admin or automation) registers the simulation**:
   ```bash
   POST /api/v1/simulation
   {
     "name": "flight-booking",
     "openapi_spec": "https://example.com/openapi.json",
     "skills_folder": "/skills"
   }
   ```
   Synchronously parses the spec, initializes the agent, and brings the MCP endpoint live. Returns 200 with the tool list, or 4xx/5xx if init fails.
3. **Skillberry tools point at this instance's MCP URL**:
   ```json
   "packaging_format": "mcp",
   "packaging_params": {
     "mcp_url": "http://harness-flight-booking.cluster.local/mcp/sse",
     "mcp_tool_name": "searchFlights"
   }
   ```
4. **Tool calls flow through MCP**: Skillberry's `file_executor.py` opens an SSE session, lists tools, and calls the named one. The harness returns a simulated response.
5. **`DELETE /api/v1/simulation`** clears the simulation; `POST /api/v1/simulation` again creates a new one (with possibly different spec). The instance itself is long-lived; the simulation inside it is replaceable.

**Why one simulation (one service) per instance — this consumer's specifics**: Skillberry's `packaging_params.mcp_url` has no place to encode a simulation ID — the URL is the only identifier the consumer carries. So each MCP endpoint serves exactly one service's tools. Multiple services = multiple harness instances, addressed by their distinct URLs. This matches the harness's general model ([DESIGN.md §2](./DESIGN.md#2-architecture-overview)) and is one of the reasons that constraint was chosen.

**Out of scope for Phase 1** (kept here for reference):
- *Pre-configured at startup*: harness reads OpenAPI from config and self-creates the simulation. Easy to add later if useful.
- *On-demand from tool metadata*: lazy creation on first MCP call. Rejected — adds cold-start latency to user-facing clicks and complicates error reporting.

## 6. Multi-Service "Try" — Phase 2 Sketch (Out of Scope for Alpha)

Phase 1 covers single-service Try (one harness instance simulates one service; Skillberry's tools all dispatch to that one MCP URL). Multi-service Try — a Skillberry `SkillSchema` whose `tool_uuids` span tools registered against multiple harness instances — is the Phase 2 case. The intended shape:

1. Resolve a Skillberry `SkillSchema` (`tool_uuids` list) to a set of harness pods / MCP URLs (one URL per underlying service).
2. Run a multi-tool session with shared context across the services involved.
3. Coordinate with the Skillberry team on the orchestration boundary (does Skillberry call multiple harnesses, or does one harness become a service-aware aggregator?).

This is captured here so that Phase 1 design choices remain compatible with it.

## 7. Alpha Acceptance — Mapped to Concrete Steps

These are the [REQUIREMENTS.md §6](./REQUIREMENTS.md#6-acceptance-criteria-phase-1) acceptance criteria, restated as actions on the alpha integration:

- [ ] An operator deploys a harness instance with a YAML config (LLM API key, default models, skill folder, session limits), calls `POST /api/v1/simulation` with a real OpenAPI spec for one service, and gets back a 200 with the parsed tool list.
- [ ] On a second `POST /api/v1/simulation` (after a `DELETE`) using the same `name`, the harness reuses the existing `SKILL.md` instead of regenerating; passing `regenerate: true` forces regeneration.
- [ ] Calling `MCP tools/list` over `/mcp/sse` returns the same tools.
- [ ] Calling `MCP tools/call` for a tool returns a schema-valid, plausible mock response.
- [ ] A Skillberry tool registered with `packaging_format=mcp` pointing at the harness URL executes successfully via Skillberry's standard execution path.
- [ ] Multi-call coherence: a series of `tools/call` invocations against the same harness instance share accumulated context (e.g., a follow-up call references state established by an earlier call), up to the configured `max_messages` and idle timeout.
- [ ] When the singleton session expires (tool-call cap or idle timeout), the offending call returns an MCP `isError: true` indicating session expired, and the next call starts fresh.
- [ ] `POST /api/v1/simulation/reset` clears the singleton thread; the next call starts fresh.
- [ ] No backend credentials are required from the Skillberry user.
- [ ] The Skillberry team has run an end-to-end Try flow against a deployed harness.

## 8. Known Operational Gotchas (Alpha)

- **Skill versioning**: changing skills means `DELETE` then `POST /api/v1/simulation` again — sessions are lost.
- **Cold start after instance deploy**: the MCP endpoint exists but `tools/list` is empty until `POST /api/v1/simulation` succeeds. Skillberry calls before that point will see an empty tool list.
- **LLM provider outages**: degrade as 5xx from the harness; Skillberry sees this as a failed tool execution and should surface it to the user.
- **Token spend**: every Try click costs LLM tokens. Phase 1 relies on the upstream LLM key cap; if it's hit, calls fail fast. Token-spend telemetry is deferred ([REQUIREMENTS.md §2.3](./REQUIREMENTS.md#23-deferred-to-a-later-phase)) — until it lands, sizing cost caps means watching the LLM provider's own dashboard.
- **Network exposure**: Phase 1 endpoints are unauthenticated. Deploy harness pods on cluster-internal addresses only; do not expose them to public ingress.

## 9. Other Use Cases — Out of Scope for the Alpha

The two other use cases in [USER_NEED.md](./USER_NEED.md) — **skill/tool optimization** and **runtime simulation for agents** — are not part of this alpha. They will be served by the same harness, through the same MCP surface, with their own per-consumer integration documents when concrete consumers materialize. Nothing in this alpha integration should foreclose them; in particular:

- **For optimization (Use Case 2)**: each optimization trial naturally maps to one harness instance (one simulation per instance). The harness's cheap-to-instantiate property is the load-bearing requirement, and the management API's `DELETE` + `POST` lifecycle already supports per-trial reset.
- **For runtime rehearsal (Use Case 3)**: the agent calls the harness as a normal MCP server. The harness imposes no opinion on whether the caller is a UI, a CI pipeline, or a production agent.

If alpha-shaped decisions ever conflict with these, they should be revisited in [DESIGN.md](./DESIGN.md) — not bent around in this document.
