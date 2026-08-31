# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](https://github.com/skillberry-ai/simulation-harness/security)
   of this repository.
2. Click **Report a vulnerability**.

This opens a private advisory visible only to you and the maintainers. If you
cannot use that form, open a regular issue containing only a request for a
private contact channel — no vulnerability details.

Please include, as far as you can determine it:

- the affected component and version (or commit SHA),
- the impact and the trust boundary crossed,
- steps to reproduce, ideally a minimal OpenAPI spec or request sequence,
- any configuration required to trigger it (`config/harness.yaml`, `HARNESS_*`
  env vars, MCP transport).

We aim to acknowledge a report within 5 working days and to keep you updated as
we investigate. Please give us a reasonable opportunity to ship a fix before
disclosing publicly.

## Supported versions

This project is pre-1.0 and moves fast. Only the latest released version
receives security fixes; there are no long-term support branches.

| Version | Supported |
|---|---|
| latest release | ✅ |
| older releases | ❌ |

## Scope and intended deployment

Before reporting, please read [THREAT_MODEL.md](THREAT_MODEL.md) — it records the
security assumptions this project is designed against, its trust boundaries, and
the threats already known and tracked.

The most important assumption: **the harness is not intended to be exposed
directly to the public internet.** It is designed for a developer machine, CI, or
an internal cluster, and callers able to submit an OpenAPI spec are treated as
semi-trusted. Reports that assume an internet-facing deployment with untrusted
callers may already be documented as accepted risk in the threat model — please
reference it so we can discuss the specific gap.

Genuinely in scope, and worth reporting:

- leakage of `LLM_API_KEY` into logs, error responses, or generated artifacts,
- a submitted spec escaping the skills folder or otherwise writing outside it,
- a submitted spec achieving code execution in the harness process,
- bypassing the one-simulation-per-process or session-expiry invariants in a way
  that exposes another caller's session state,
- vulnerabilities in our dependency pinning or release/publish pipeline.

Out of scope: the LLM producing inaccurate or unexpected simulated API responses.
That is a correctness issue — please open a normal issue for it.
