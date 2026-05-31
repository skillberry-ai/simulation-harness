# Simulation Harness — User Need

This document describes who the Simulation Harness is for and what they want to do with it. It is intentionally platform-agnostic: the harness is a reusable building block, not a feature of any particular agentic platform. The concrete alpha integration with a specific platform is described separately in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md).

## 1. The Problem

Agent developers and the platforms they build on need a way to **execute tools and skills without their real-world side effects**. Real backends require credentials, cost money, take time to set up, and can produce irreversible effects (sending an email, charging a card, deleting a record). This blocks three different workflows that all share the same underlying need:

- **Discovery** — exploring what a tool or skill does before committing to integrate it.
- **Iteration** — measuring whether a change to a skill or tool improved behavior, across many trials.
- **Safe action** — letting an agent rehearse a course of action before taking the real one.

What's missing is a managed environment that **looks like the real tool to the agent** but generates plausible behavior via an LLM-driven simulation, with no real backend involved.

## 2. Personae

### 2.1 Agent Developer

Someone who builds agents, skills, and/or tools — typically against an agentic platform that already manages tool registration, execution, and orchestration.

**What they care about**:
- Quick feedback when wiring up new tools into an agent.
- Confidence that a skill/tool change improved behavior, not just changed it.
- Equipping their agents with the ability to "think before acting" on irreversible operations.

**What they don't want to do**:
- Stand up real backends for tools they're only evaluating.
- Manage credentials, sandboxes, or test data.
- Rebuild a simulation layer for every new agent or skill.

### 2.2 DevOps Engineer (Agentic Platform Administrator)

Someone who runs the agentic platform itself — operating the tool registry, the execution path, the observability stack, and the surrounding infrastructure for a team or organization.

**What they care about**:
- Offering a simulation capability as a first-class platform service that agent developers can rely on.
- Operational simplicity: deploy, configure, scale, monitor, retire — using the same patterns as the rest of the platform (typically Kubernetes-shaped).
- Predictable cost and a clear failure surface (LLM outage, bad spec, exhausted token budget).
- Integration with the platform's existing tool-execution path, ideally without bespoke code on the platform side.

**What they don't want to do**:
- Operate a snowflake service with its own auth model, configuration shape, or deployment story.
- Custom-glue every consumer of the simulation layer.

## 3. Use Cases

The harness must support all three. They share one underlying capability — a managed, sessioned simulation that exposes tools as MCP endpoints — and differ in how that capability is invoked.

### 3.1 Use Case 1 — "Try" (Catalog Exploration)

**Primary persona**: Agent developer (as a catalog browser).
**Supporting persona**: DevOps engineer (provides the Try affordance as a platform service).

An agent developer is browsing the platform's tool/skill catalog and wants to evaluate one before committing to wire it up. They click **Try** in the catalog UI, supply arguments, and see a realistic, schema-valid mock response — within seconds, with no credentials, no real backend, no Docker sandbox setup.

**Why the harness fits**: the platform routes the Try click through the harness's MCP surface; the harness generates a plausible response; the user sees it in the same UI they would for a real call. Mock responses are good enough to inform a *decision* (is this tool worth integrating?), not good enough to substitute for real integration testing.

**Success looks like**: an agent developer goes from "I see a tool I might want" to "I have a plausible response in front of me" in under a minute, with zero configuration.

### 3.2 Use Case 2 — Skill/Tool Optimization Cycles

**Primary persona**: Agent developer (running an optimization loop).
**Supporting persona**: DevOps engineer (hosts the harness as part of dev/CI infrastructure).

An agent developer (or an automated optimization mechanism) is iterating on a skill or tool — adjusting prompts, parameter shapes, behavior — and needs to evaluate the impact of each modification. The optimizer applies a candidate change, runs a workload (a set of representative inputs or scripted scenarios), measures behavior, and uses that measurement to pick the next candidate.

**Why the harness fits**: each candidate can be evaluated against the harness without consuming a real API budget, without producing real side effects, and without a flaky external service muddying the signal. The optimizer can:

- Replace the simulation behind a tool quickly (delete + recreate, or a parallel pod with new skills).
- Reset session state between trials to ensure independence.
- Run many trials in parallel by spinning up multiple harness instances.
- Read latency/token-spend telemetry alongside behavioral measurements.

**Success looks like**: an optimization loop can run hundreds of trials per skill/tool variant per hour, with clean per-trial state, at predictable cost.

### 3.3 Use Case 3 — Runtime Simulation for Agents (Course-of-Action Experimentation)

**Primary persona**: Agent developer (building an agent that needs to act safely).
**Supporting persona**: DevOps engineer (operates the harness as a runtime safety layer).

An agent that's about to take an action with potentially irreversible real-world impact (sending a message, transferring funds, mutating shared state) wants to **rehearse** the action first. It calls the simulated version of the same tool, observes the simulated result, decides whether to proceed, and only then issues the real call.

This is fundamentally different from Use Case 1 in invocation pattern: the **agent itself** chooses to route through the harness, not a UI. It's different from Use Case 2 in lifecycle: the simulation is long-lived and serves real production traffic, not short bursts of evaluation traffic.

**Why the harness fits**: the harness exposes the same tool surface (MCP) as the real tool, so the agent's tool-calling code doesn't change — only the URL/routing. The agent can issue a call, examine the response, and if the rehearsal looked sane, repeat against the real backend. Session state lets the agent rehearse multi-step plans coherently.

**Success looks like**: an agent developer can mark certain tools as "rehearsable" in their agent and have the agent automatically simulate before committing, with the simulation feeling responsive enough that the rehearsal step doesn't dominate the agent's wall-clock time.

## 4. Cross-Cutting Properties

Across all three use cases, the harness must:

- **Look like a normal tool backend to the caller.** The integration shape is MCP — the same protocol the real tool would expose. No bespoke client SDK.
- **Be platform-agnostic.** It does not assume any particular agentic platform's data model, auth model, or UI. It is consumed by such platforms; it is not a part of any one of them.
- **Be operationally boring.** Deploys like a normal service. Scales horizontally by spinning up more instances. Fails loudly when misconfigured.
- **Be cheap to instantiate.** Use Cases 2 and 3 imply lots of harness instances (per-experiment, per-environment, per-tool); the per-instance cost must support that.

## 5. Non-Goals

- **Not a load-testing or contract-testing tool.** The harness is for *behavioral* simulation, not performance or schema-conformance testing.
- **Not a record/replay mock server.** Responses are LLM-generated, not pre-captured.
- **Not a substitute for real integration testing.** It answers "is this tool worth investigating?" or "is this course of action sane?" — not "will my production code work?"
- **Not opinionated about the consumer platform.** Any integration specifics (auth shapes, schema mappings, UI affordances) belong in the consumer or in a per-platform integration document — not in the harness itself.

## 6. Why Now

A managed simulation backend, exposed through MCP and decoupled from any single platform, unblocks all three of these workflows simultaneously. The first concrete consumer is the alpha integration described in [ALPHA_USE_CASE.md](./ALPHA_USE_CASE.md); future consumers (other platforms, agent frameworks, optimization tooling) will plug in through the same MCP surface without bespoke harness changes.
