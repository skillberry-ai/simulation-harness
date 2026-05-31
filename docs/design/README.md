# Simulation Harness — Master Document

The Simulation Harness is a managed environment for simulating MCP tools and skills. It is platform-agnostic: any MCP-capable consumer (an agentic platform, an optimization mechanism, or an agent at runtime) can call it without bespoke integration code. The first concrete consumer is the alpha integration with Skillberry Store, but the harness itself imposes no opinions about its consumers.

This page is the index. The full content is split across four documents in this directory, in dependency order:

| # | Document | Purpose |
|---|---|---|
| 1 | [User Need](./USER_NEED.md) | Who the harness is for (two personae: agent developer and DevOps engineer) and what they want to do with it. Three use cases: catalog "Try", optimization cycles, and runtime course-of-action rehearsal. Platform-agnostic. |
| 2 | [Technical Requirements](./REQUIREMENTS.md) | What the harness must do — functional and non-functional requirements, the authoritative Phase 1 scope decisions, acceptance criteria. The contract the design must satisfy. Platform-agnostic. |
| 3 | [Design](./DESIGN.md) | How the harness is built — architecture, API surface, component design, code reuse, MCP integration, configuration, deployment, roadmap. Platform-agnostic. |
| 4 | [Alpha Use Case](./ALPHA_USE_CASE.md) | The concrete worked example: Skillberry Store's "Try" button backed by the harness as an MCP backend. The **only** document containing Skillberry-specific content. Future per-consumer integrations (other platforms, optimization tooling, runtime rehearsal) will get their own peer documents alongside this one. |

## How These Documents Relate

```
USER_NEED.md            REQUIREMENTS.md
  (personae +              (contract for
   3 use cases)              the harness)
       \                   /
        \                 /  (constrains)
         ▼               ▼
            DESIGN.md
       (platform-agnostic)
                │
                │ (instantiated by per-consumer integration docs)
                ▼
        ALPHA_USE_CASE.md          ...future peer docs...
        (Skillberry / Use Case 1)  (e.g. optimization, runtime rehearsal)
```

- **USER_NEED** and **REQUIREMENTS** are inputs.
- **DESIGN** is what the harness is, justified against those inputs and stated independently of any consumer.
- **ALPHA_USE_CASE** is the first concrete instance; additional per-consumer documents will follow the same shape as more consumers come online.

## What Lives Where (Platform-Agnostic Boundary)

To keep the harness reusable across consumers, the following boundary is enforced:

- **In USER_NEED / REQUIREMENTS / DESIGN**: only properties of the harness itself, the personae using it, and the use cases it supports. No mention of any specific consumer platform's data model, schema, auth model, or UI.
- **In ALPHA_USE_CASE (and future peer docs)**: everything specific to one consumer — its tool registration shape, its dispatch path, its operational quirks, its acceptance steps.

If a Skillberry-specific (or other consumer-specific) detail appears in the first three documents, it should be moved into the relevant per-consumer document.

## Quick Status

- **Phase**: 1 — Foundation + service-level simulation (one OpenAPI spec → one skill → one harness instance)
- **Status**: Draft — awaiting review
- **Last updated**: 2026-05-30

## Related Files

(No additional related files at this time)
