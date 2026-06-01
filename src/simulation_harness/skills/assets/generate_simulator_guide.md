# Guide: Generating an MCP Simulator SKILL.md from an OpenAPI Spec

This guide is read by the *generator* LLM. The generator reads an OpenAPI JSON
spec and produces a single `SKILL.md` file. That `SKILL.md` is later loaded by a
different *runtime* LLM which impersonates the MCP server for an agent that is
being tested.

Two audiences, two different voices:

- **You (the generator)**: a careful spec analyst. You extract everything the
  runtime will need and write it down in an unambiguous, literal form.
- **The runtime (your reader)**: an LLM with no access to the OpenAPI spec, no
  memory across sessions other than what it is told to keep in session state,
  and no ability to ask clarifying questions. It does exactly what SKILL.md
  tells it to do.

Every sentence you write in SKILL.md is an instruction the runtime will follow
verbatim. Vague SKILL.md → unreliable simulator. Over-cautious SKILL.md ("the
runtime may return an error if it seems plausible") → spurious failures against
the agent-under-test. Be specific. Be literal. Prefer rules over suggestions.

---

## Output contract (strict)

The generator must produce the SKILL.md file and nothing else:

- No commentary before the `---` frontmatter.
- No commentary after the final line of markdown.
- No outer code fence wrapping the file.
- YAML frontmatter first, in this exact form:

```
---
name: <api-name>-simulation
description: Simulate the <Human-Readable API Name> by intercepting tool calls and generating realistic, consistent mock responses.
---
```

`<api-name>` is the lowercase-hyphenated form of `info.title` with trailing
`-api` / `-service` removed (examples: `restaurant-reservation`,
`flight-booking`).

Every one of the top-level sections listed in **SKILL.md Structure** below must
appear, in order, even if a section is short.

---

## Step 1 — Extract everything from the spec

Before writing, identify and keep:

1. **Every operation**: for each path + method, record operationId, summary,
   tool-style name (see note on MCP tool naming below), required vs optional
   inputs (path, query, body), response schema, and any `example`/`examples`
   blocks.
2. **Every component schema**: required fields, field types, formats (date,
   date-time, email, uri, uuid), enums, `minimum`/`maximum`, `minLength`/
   `maxLength`, `pattern`, defaults, and nullable flags.
3. **Entity relationships**: which field in schema A is a foreign key into
   schema B. This is what drives referential integrity in the runtime.
4. **Idempotency signals**: operationIds like `cancel`/`place`/`book`, 409
   responses, explicit `Idempotency-Key` headers, or wording like "repeated
   calls" in descriptions.
5. **Schema-vs-example conflicts**: if `responses.200.schema` says object but
   `responses.200.examples` shows a string or an array-of-arrays, the runtime
   must follow the example. Record every such quirk now so you can surface it
   explicitly in SKILL.md.
6. **Unusual response shapes**: endpoints that return a bare JSON string,
   primitive, or semicolon-delimited list-inside-a-string. These are common in
   enterprise APIs (e.g., SAP SuccessFactors) and the runtime will mishandle
   them unless SKILL.md names the pattern and gives an example.

### Note on MCP tool naming

MCP tool names are usually derived from the endpoint path or operationId
(`/search_restaurants` → `search_restaurants`, `searchRestaurants` →
`search_restaurants`). List *both* the HTTP path and a likely tool name in each
operation section so the runtime can match either form.

---

## Step 2 — Design session state

The runtime's main job is to remember what it said earlier. Under-specified
state is the #1 cause of simulator failure.

For every entity the API can create, read, update, or delete, define:

- **Store name** (e.g., "Reservation Database").
- **Key(s)** it is indexed by (primary ID, plus any secondary lookup keys like
  email or phone).
- **All fields** from the schema the runtime must persist, plus any
  *simulator-only* metadata the runtime needs to stay consistent (idempotency
  fingerprints, soft-delete flags, cancellation timestamps, generated
  availability profiles, etc.).
- **Write operations**: which operations add or modify entries.
- **Read operations**: which operations read from this store.

Also define cross-cutting state when relevant:

- **Reference-data catalogs** (airport codes, phone types, country lists).
  These are fixed across the session and must not drift between calls.
- **Seed data**: the minimum set of entities the runtime must pre-populate so
  an agent-under-test whose first call is a read does not get an empty
  response. Give concrete IDs, names, and enough linked data for common
  read-then-write flows (e.g., the reservation API needs restaurants seeded
  before any booking can happen; the booking API needs users and flights
  seeded before any cancellation can happen). Be explicit about this data.
- **Idempotency maps**: for each write operation the spec treats as
  idempotent, define the exact fingerprint fields (ordered list) and what the
  runtime returns on a duplicate.

State must be described as structures, not prose. Use nested bullet lists with
types so the runtime can parse them unambiguously.

---

## Step 3 — Write the SKILL.md

### SKILL.md structure

Every generated file uses these top-level sections in this order:

```
---
name: …
description: …
---

# <Human-Readable API Name> Simulation

<one-sentence mission statement for the runtime>

## Core Principles
## Session State Management
## Seed Data and Data Generation
## Schema Reference
## API Operation Simulation
## Error Handling
## Realism Guidelines
## Response Format
## Consistency Checklist
## Validation Coverage
```

If the API has no obvious seed-data need (e.g., a pure calculator), keep the
section but make it a single line stating that no seed data is required.

### Section-by-section instructions

#### Core Principles

4–6 short bullets. Always include:

- Consistency across the session is paramount.
- Return only fields defined in the response schema, with correct JSON types.
- Generate realistic, domain-appropriate data.
- Maintain referential integrity.
- Return errors only when their specific triggering condition is met.

Tune to the domain (e.g., flight booking adds "prefer examples over schema when
they disagree"; SAP-style APIs add "some endpoints return semicolon-delimited
strings — follow the spec examples").

#### Session State Management

One subsection per store. For each, list fields with types and mark primary
keys. Include simulator-only metadata in a clearly labeled subsection so the
runtime does not leak internal fields into responses. End with an explicit
statement of which fields are *internal only* and must never appear in
responses.

#### Seed Data and Data Generation

State the minimum seeded dataset in concrete, reproducible form. Give specific
IDs, names, and values — not "some users" but "at least these three users:
`u_001` Jane Doe…". If the runtime will generate data on demand (e.g., "if
this city has not been searched before, generate 6–12 restaurants for it"),
state the generation rules, the value ranges, and the naming style. Anchor
temporal values: "use dates consistent with the current session year."

#### Schema Reference

Compact list of every named schema from `components.schemas`. For each, list
required fields and optional fields with their types and formats. Enum values
must be enumerated verbatim. This section exists so the runtime can verify
shape without rereading operation sections.

#### API Operation Simulation

One subsection per operation. Use this skeleton:

```
### `<path>` <METHOD>

**Operation ID:** `<operationId>`
**Tool name (MCP):** `<likely_tool_name>`
**Purpose:** <one sentence from the spec summary/description>

**Input Parameters:**
- `<name>` (required|optional, <type>[, format][, constraints]) — <description>

**Response Generation:**
1. Validate <specific required fields> are present.
2. Validate <specific constraints>.
3. <Lookup / generation / state-mutation steps in order>.
4. <Return shape, with explicit reference to the schema and any quirks>.

**State Changes:**
- <exact writes to each store, or "None">

**Example Response:**
```json
<a realistic, schema-conformant JSON body>
```
```

Rules for this section:

- Every required field in the spec must appear in the parameter list.
- Every validation the runtime should perform must be written as a numbered
  step. If it is not listed, it will not happen.
- State mutations are explicit: name the store, name the key, say what is
  written.
- The JSON example must be valid against the schema. All required fields
  present. Correct types. Realistic values. For list endpoints, include at
  least two items so the runtime sees the repetition pattern.
- If the spec defines multiple response shapes (e.g., `status=available` vs
  `status=landed` vs `status=cancelled`), include one example per shape with a
  label.
- If the spec's schema disagrees with the spec's example, follow the example
  and insert a one-line "**Schema quirk:**" note pointing this out.

#### Error Handling

This section is the single most common source of simulator regressions. Be
surgical.

- Start with the exact error schema from the spec, rendered as a JSON shape.
- List every error condition the runtime is allowed to return. For each:
  - State the triggering condition using a bold **When** clause.
  - Show the exact error JSON.
  - Add "Do **NOT** return this error if <negation of the condition>."
- After the common rules, add a subsection per endpoint listing which error
  conditions apply to that endpoint. End each endpoint block with the "no
  results → `[]`, not an error" rule where applicable.
- Do not invent error conditions that are not in the spec. If the spec does
  not list a 404 for a given endpoint, do not add one.
- Explicitly forbid the runtime from adding extra fields (no status codes,
  error codes, stack traces, or "details" objects unless the schema defines
  them).

#### Realism Guidelines

Domain-specific guidance the runtime will use when generating new data. Keep
it concrete: value ranges, naming patterns, geographic realism, business
hours, plausible pricing tiers, temporal orderings (e.g., `created_at` ≤
`cancelled_at`). No generic filler ("use realistic data") — if you cannot name
a concrete rule, drop the bullet.

#### Response Format

Short and absolute. Always valid JSON. No markdown, no explanation, no HTTP
envelope, no extra keys. If the spec expects a bare JSON string for some
endpoints, say so here and point to the relevant operations.

#### Consistency Checklist

10–15 checkable items the runtime should mentally run through before
responding. Cover: schema compliance, ID reuse, referential integrity, state
persistence, idempotency, empty-result handling, temporal consistency, and
the strict error-gating rule.

#### Validation Coverage

A simple list confirming every OpenAPI path + method is covered, plus a list
of every entity/relationship tracked. This section is for human review of the
SKILL.md — keep it concise.

---

## Step 4 — Self-review before emitting

Walk the generated SKILL.md against this checklist mentally. If any answer is
"no," fix the file before returning it.

- Every path + method in the spec has its own operation section.
- Every required request field is listed for its operation.
- Every response schema has a matching JSON example, and the example is valid
  against the schema.
- Every entity the API can create, read, update, or delete has a store, a key,
  and an explicit list of read/write operations.
- Every "When …" error clause is paired with a "Do NOT …" negation.
- Schema-vs-example conflicts in the source spec are called out in the
  affected operation section.
- Empty-result contracts (`[]` vs error) are explicit per list endpoint.
- Idempotency behavior is defined for each write the spec treats as
  idempotent, with a concrete fingerprint.
- Seed data is sufficient for a read-first first call to succeed.
- The file starts with `---` and ends with a markdown line, with no
  surrounding commentary.

---

## Patterns worth knowing

### CRUD

- **Create**: validate required fields → check idempotency fingerprint → if
  duplicate, return existing entity → else generate ID, persist, return full
  entity with all schema fields populated.
- **Read by ID**: look up in store → if missing, return the spec's not-found
  error (not a generic 500) → else return the stored entity unchanged.
- **Update**: verify exists → apply only the fields present in the request →
  return full updated entity.
- **Delete / cancel**: verify exists and is not already deleted → mutate state
  (soft delete or remove) → return receipt → subsequent reads must reflect
  the deletion.

### Search / filter

- Apply filters progressively against the store.
- Empty result set is `[]`, never an error.
- Sort deterministically (by rating, by distance, by ID) so repeated calls
  return the same order.

### String-encoded lists (enterprise APIs)

Some OpenAPI specs type a response as `string` but the example is a
semicolon-delimited list (`"HOME | Home Phone; MOBILE | Mobile Phone"`). The
runtime must produce the string form, not an array. Call this out in the
affected operation sections and in Core Principles.

### Response-shape conditionals

When a single endpoint returns different shapes based on an internal status
(`available` / `landed` / `cancelled`), write one **Example Response** per
shape with a labeled header. The runtime will pattern-match these.

### Idempotency fingerprints

State the fingerprint as an ordered list of field names. If the spec has no
explicit idempotency key, pick a semantic fingerprint (for a reservation:
`restaurant_id + date_time + party_size + guest_name + guest_email`). Specify
how missing optional fields are normalized (empty string, omitted, etc.) so
the fingerprint is stable.

### Temporal reasoning

Do not hard-code year 2024 (or any year) across the whole file. Tell the
runtime to use timestamps consistent with the current session date, and to
maintain ordering constraints (e.g., `cancelled_at ≥ created_at`). Use
anchored example dates in JSON blocks but note that the runtime may shift
them forward.

---

## Anti-patterns (do not produce these in SKILL.md)

- "The runtime should probably return an error here." → Ambiguous. Either a
  condition triggers the error or it does not. State the condition.
- "Generate realistic data." → Give rules: value ranges, naming style,
  plausible formats.
- "Maintain state." → Name the store, the key, the writer ops, the reader
  ops.
- Copying the OpenAPI schema verbatim without adding response generation
  logic. The runtime needs instructions, not specs.
- Skipping an endpoint because it seems trivial (health checks, list-airports,
  ping). Every endpoint gets a section.
- Adding endpoints or fields that are not in the spec. Stay faithful.
- Wrapping the entire SKILL.md in a code fence, or adding a "Here is the
  generated file:" preamble. The file is the entire output.