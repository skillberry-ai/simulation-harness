# Changelog

## v0.1.2 — 2026-08-31

### Breaking changes

- **config:** LLMConfig forbids extra keys, so a harness.yaml still setting `llm.skill_generation_max_tokens` now fails validation at startup with a message naming that key. Delete the line to fix it. deploy/k8s/configmap.yaml never set it.

### Features

- **config:** allow LLM model selection via HARNESS_* env vars
- **openapi:** add media-type example accessors
- **generation:** add OperationEvidence to the IR
- **generation:** extract operation descriptions into the IR
- **generation:** pass description to the behavior stage
- tau2_retail example
- **scripts:** surface breaking changes in release notes

### Fixes

- **scripts:** re-lock uv.lock as part of the release commit
- **generation:** pass summary and description to the operations stage
- **generation:** log when the behavior stage degrades silently
- **tests:** parenthesize evidence description check, add strip coverage
- **generation:** log scenarios-stage degrade, tidy caplog and IR nit
- **deps:** bump dompurify to 3.4.14 for GHSA-55q2-fjhq-7xh7
- **deps:** floor pip at 26.2 for PYSEC-2026-3721

### Refactoring

- **config:** drop skill-generation token config that did nothing

### Documentation

- **generation:** document SpecModel.evidence and the shape/intent split

### Chores

- prepare the repo for its public home

## v0.1.1 — 2026-08-05

### Fixes

- **deps:** upgrade cryptography to 50.0.0 for PYSEC-2026-3552

## v0.1.0 — 2026-08-05

### Features

- initial release
- api name override
- Skillberry sample files
- keep api.json in skill directory
- Add state store feature with MCP tools integration
- cli for simulation creation
- switch to local .env file for secrets
- resource-based secrets management
- rename mcp_endpoint to mcp_url in SimulationResponse
- return absolute mcp_url in create_simulation response
- return absolute mcp_url in get_simulation response
- add PortInUseError for sidecar MCP port conflicts
- add optional mcp_port field to CreateSimulationRequest
- add SidecarMCPServer for per-simulation port binding
- store mcp_port on SimulationInstance and stop sidecar on shutdown
- wire mcp_port through SimulationHost to start sidecar server
- build correct mcp_url from mcp_port; return 409 on port conflict
- add PortInUseError exception handler to FastAPI app
- add /healthz and /readyz probes with draining flag
- add HARNESS_* env-var overrides for HarnessConfig
- multi-stage uv-based Dockerfile (non-root, healthcheck)
- docker-compose for local harness dev
- k8s namespace, configmap, and secret template
- k8s Deployment and Service for harness
- optional HPA and kustomize bundle for k8s deploy
- add SimulationRecord lifecycle state machine
- add SimulationNotReadyError and CreationTimeoutError
- add creation.max_duration_seconds config (default 120s)
- add SimulationCreator background task runner
- SimulationResponse carries progress and error; session_state/mcp_url optional
- POST /simulation returns 202; record exposes pending/ready statuses
- 503 + Retry-After when MCP transport called against not-ready simulation; 404 when no record
- simulate CLI and test client poll until ready after async create
- **errors:** add DatabaseValidationError and SimulationBusyError
- **main:** map DatabaseValidationError to 422, SimulationBusyError to 409
- **skill_registry:** add read_schema and read_db helpers
- **skill_registry:** add validated atomic write_db
- **simulation_host:** add replace_database with lifecycle-lock orchestration
- **api:** add GET/PUT /simulation/database and GET /simulation/schema routes
- update the test client with the latest api
- make dockers
- **test-client:** rewrite test client as PatternFly + React SPA with Express proxy
- tau2 example
- add per-simulation skill-sources filesystem helper
- slim runtime prompt; move per-operation detail to skill
- load per-API skill via lean create_agent + filesystem backend
- make agent_recursion_limit a configurable session setting
- **generation:** add GenerationConfig with defaults and YAML block
- **generation:** add IR models and consistency validation
- **generation:** add LLM client and structured-call helpers
- **generation:** add bounded self-repair loop
- **generation:** add stage 1 analyze (spec -> IR)
- **generation:** add stage 2 schema + seed generation
- **generation:** add stage 3 per-operation sections + chunking
- **generation:** add stage 4 assemble + bundle validation
- **generation:** add pipeline orchestrator with bounded fan-out
- **generation:** report per-stage generation progress phases
- **generation:** split analyze stage config into extract + classify
- **generation:** add stage-1a data-model extraction
- **generation:** add stage-1b classify with tag-aware bin packing
- **generation:** add analyze merge with strict coverage check
- **generation:** decompose analyze into extract + fanned-out classify
- **generation:** add Scenario model and scenario generation config
- **generation:** add standalone schema stage
- **generation:** add scenarios stage
- **generation:** add scenario-aware seed stage
- **generation:** render Example Scenarios section in SKILL.md
- **generation:** wire scenarios stage and scenario-aware seeding into pipeline
- **generation:** persist scenarios.json alongside skill artifacts
- **core:** add GENERATED lifecycle status and transitions
- **errors:** add SimulationArtifactsNotFoundError mapped to 404
- **core:** add SkillRegistry artifact-read and discovery helpers
- **core:** add generate/start flags to SimulationCreator
- **core:** add setup_simulation and start_simulation to SimulationHost
- **api:** add /simulation/setup and /simulation/start endpoints
- **cli:** add offline setup CLI for build-time artifact generation
- **startup:** config-driven auto-start of baked simulations on boot
- updates to the test client
- **core:** add SkillRegistry.read_bundle for verbatim bundle export
- **api:** add GET /simulation/bundle to export the full skill bundle (#14)
- **utils:** add get_bundle.py CLI to export the skill bundle
- tasks example (Kagenti test)
- **startup:** add autostart_enabled config field (default false)
- **startup:** honor autostart_enabled flag in resolver and boot path
- **startup:** add HARNESS_AUTOSTART_ENABLED env override
- **generation:** add behavior stage config knobs
- **generation:** add global behavior stage
- **generation:** inject behavior section into skill preamble
- **generation:** require per-op derived-fields note
- **generation:** wire behavior stage into pipeline
- computation example
- **simulate:** stop running simulation before creating a new one
- **skills:** add provenance manifest builder
- **skills:** write manifest.json with each generated bundle
- **api:** include manifest.json in the exported skill bundle
- **scripts:** add release-notes generator and shell test harness
- **scripts:** add release.sh to cut numbered releases
- **scripts:** add mirror-release.sh to publish a release to the mirror

### Fixes

- sse issue
- simplify makefile
- translate OSError to PortInUseError on uvicorn startup; use request scheme in mcp_url
- apply_env_overrides updates the global config singleton
- install harness non-editable so it imports from runtime stage
- add structured reason field to MCP tools/call error payloads
- GET /api/v1/simulation/tools returns 404 when no simulation active
- update unit tests for async simulate.py and new SimulationResponse shape
- docker folder permissions
- include transport type in the mcp url
- configure max token count
- harden read-only fs rule and skill-sources guard per final review
- stage active skill in temp dir to remove self-referential cycle
- force SKILL.md frontmatter name to match skill directory
- **test-client:** patch dependabot vulns (vitest 3, vite 6, drop unused dompurify)
- **generation:** surface truncated LLM responses as StructuredCallError
- **generation:** unwrap json_object payload in classify stage
- track uv.lock
- increase default timeouts and token counts
- **openapi:** sanitize operationId into valid MCP tool names
- sanitize skill name
- **generation:** trim Jinja whitespace in Example Scenarios block
- skill name in test
- extend timeout
- stage timeout
- correctly handle ops outside components
- only drop privileges via gosu when running as root
- serve MCP Streamable HTTP via StreamableHTTPSessionManager
- resolve $ref request bodies in MCP tools/list inputSchema
- **test-client:** clear prior tool result when a new call starts
- fold path-item-level parameters into operation schemas
- resolve request/response schemas and use 2xx success response in skill generation
- **logging:** render exc_info as chained traceback, not raw tuple
- **generation:** classify stage timeouts distinctly instead of masking them
- **deps:** bump mcp 1.27.2 -> 1.28.1 for CVE-2026-59950
- **test-client:** resolve npm advisories via audit fix
- **generation:** correct behavior-section preamble whitespace
- **test-client:** resolve 8 Dependabot alerts in test-client deps
- **test-client:** bump dompurify override to 3.4.12
- **deps:** bump pyasn1 to 0.6.4 to resolve PYSEC-2026-3455/3456/3457
- **skills:** address code-review findings for provenance manifest
- **agent:** use public tools= allowlist for read-only filesystem
- **scripts:** harden release.sh changelog separator, remote check, and shellcheck
- **scripts:** harden release and mirror against partial failure
- **scripts:** close the residuals from the scoped re-review
- **scripts:** gate both release resume arms on a real release commit
- **deps:** patch fast-uri and hono advisories in test-client
- **deps:** upgrade test-client to React 19 and react-router 8
- **deps:** drop the cookie-es workaround after upgrading npm
- **scripts:** stop the release commit failing on its own CHANGELOG

### Refactoring

- fix fail() delegation and mark_ready clarity in SimulationRecord
- SimulationHost holds SimulationRecord and runs creation in background
- **generation:** delegate generate_skill to multi-step pipeline
- **generation:** convert analyze stage to a subpackage
- **generation:** remove obsolete schema_seed stage
- **agent:** exclude manifest.json from the staged skill copy

### Documentation

- deploy README — docker, k8s, env vars, probes
- link to docker / k8s deployment guide
- remove stale Deployment section, fold notes into new Docker / Kubernetes
- document async simulation creation flow and 503 not-ready behavior
- describe /simulation/database and /simulation/schema endpoints
- explain deepagents <=0.5.4 version cap
- note runtime now loads SKILL.md via skills middleware
- document setup/start split, setup CLI, and auto-start
- document ConfigMap-only LLM model config in deploy readme
- **startup:** document autostart_enabled flag and env override
- **generation:** document the behavior stage
- correct three code anchors in simulation-generation.md
- document the release and mirroring workflow
- **releasing:** document escape hatches and the recovery runbook
- **releasing:** correct where container images are built

### Tests

- remove tautological test_mcp_url_is_absolute
- use exact URL assertion in test_create_simulation_success
- update stale mcp_endpoint references to mcp_url
- add integration tests for mcp_port per-simulation sidecar
- integration coverage for HARNESS_* env-var overrides
- lifespan shutdown sets draining flag for /readyz
- integration tests poll-to-ready and exercise async lifecycle
- **integration:** cover GET/PUT /simulation/database and /schema
- verify per-simulation skill discovery and isolation
- update stale assertions for mcp url and creation timeout
- **generation:** end-to-end multi-step generation integration test
- **integration:** materialize mocked skill dirs so agent init succeeds
- **integration:** cover scenario generation and disabled path
- **integration:** cover setup->start flow and start-without-artifacts 404
- set LLM_API_KEY in streamable_http fixture so CI passes
- **startup:** cover autostart_enabled flag at boot
- **generation:** annotate spec fixtures to fix mypy index error
- **generation:** stub behavior stage in full-pipeline integration tests
- **generation:** guard behavior heading invariant and graceful-skip path
- **scripts:** cover merge-commit exclusion and note sourced-only files

### Build

- add deepagents dependency for skill loading
- install git hooks as part of make dev-install

### CI

- build and publish container image to GHCR

### Chores

- enhanced api docs
- disambiguate skill folders
- missing files
- more missing files
- lint
- ignore ruff cache
- readme
- bob custom instruction (use uv)
- cleanup
- tests
- remove debug prints
- CLAUDE.md
- add .dockerignore
- docs
- fix docstrings and import style in errors task
- lint, format, and add ruff to dev deps
- dev dependencies
- lint and format fixes
- raise simulation creation timeout from 120s to 600s
- Aha! example (original and validated)
- test fixtures
- fix tests to use fixtures
- examples
- **config:** surface scenario-generation knobs in harness.yaml
- simulation generation doc
- readme
- hooks, skills, and other chores
- type annotations
- security scanning + structlog logging
- fix dependencies
- disable codeql blocking while GHAS is not available
- docs updates
- remove one-shot annotate_tests backfill script
- bump docker/* versions
- fix image name, support multiple architectures, and publish a digent id
- autostart e2e integration testing
- update deployment readme
- sign-off protocol
- whitespace
- **skills:** remove orphaned legacy generator prompt assets
- **deps:** raise deepagents cap to 0.7.1
- **ci:** ignore minor/patch codeql-action bumps in Dependabot

### Other

- Implement skill package schema/db separation
- style: drop unused os import in health-endpoints test
- style: apply ruff format to scenario test files
