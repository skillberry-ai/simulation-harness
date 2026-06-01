# Guide: Generating an MCP Simulator Skill Package from an OpenAPI Spec

This guide is read by the *generator* LLM. The generator reads an OpenAPI JSON
spec and produces three files: `SKILL.md`, `schema.json`, and `db.json`. These
files are later loaded by a different *runtime* LLM which impersonates the MCP
server for an agent that is being tested.

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

The generator must produce a JSON object with three fields:

```json
{
  "skill_md": "---\nname: ...\n...",
  "schema_json": { "$schema": "...", ... },
  "db_json": { "restaurants": [...], ... }
}
```

- **`skill_md`**: A string containing the complete SKILL.md content
- **`schema_json`**: A JSON object (not a string) containing the JSON Schema
- **`db_json`**: A JSON object (not a string) containing the seed data

**Critical requirements:**

- The entire response must be valid JSON — no preamble, no commentary, no
  markdown fences around the JSON
- `skill_md` must start with `---` frontmatter and contain no outer code fence
- `schema_json` must be a JSON Schema Draft 2020-12 object
- `db_json` must validate against `schema_json`

### SKILL.md frontmatter

The `skill_md` string must begin with YAML frontmatter in this exact form:

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

## Step 2 — Design session state, schemas, and seed data

The runtime's main job is to remember what it said earlier. Under-specified
state is the #1 cause of simulator failure.

This step produces content for three outputs: store metadata (SKILL.md),
entity schemas (schema.json), and seed data (db.json).

### 2a — Store metadata (for SKILL.md)

For every entity the API can create, read, update, or delete, define:

- **Store name** (e.g., "Restaurant Catalog Store").
- **Primary key** (e.g., `id`).
- **Secondary indexes** (e.g., `city` (case-insensitive), `cuisine`).
- **Simulator-only metadata** fields that the runtime needs but must never
  appear in API responses (e.g., `distance_from_center_km`,
  `availability_profile`, `seeded`).
- **Write operations**: which operations add or modify entries.
- **Read operations**: which operations read from this store.
- **Internal-only fields**: explicit list of fields that must never appear in
  responses.

Also define cross-cutting state when relevant:

- **Reference-data catalogs** (airport codes, phone types, country lists).
  These are fixed across the session and must not drift between calls.
- **Idempotency maps**: for each write operation the spec treats as
  idempotent, define the exact fingerprint fields (ordered list) and what the
  runtime returns on a duplicate.

### 2b — Design schema.json

Create a JSON Schema (Draft 2020-12) that describes the database shape.

**Top-level structure:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "<API Name> Simulator State",
  "type": "object",
  "required": ["<store1>", "<store2>"],
  "properties": {
    "<store1>": {
      "type": "array",
      "items": { "$ref": "#/$defs/<EntityType1>" }
    }
  },
  "$defs": {
    "<EntityType1>": {
      "type": "object",
      "required": ["id", "..."],
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" }
      },
      "additionalProperties": false
    }
  }
}
```

**Rules:**

- Top-level `properties` keys match store names from step 2a
- Each store property is an array of entities
- Each entity type is defined in `$defs` with a `$ref` from the store
- All entity schemas must have `"additionalProperties": false`
- Include all fields from the OpenAPI component schemas
- **Exclude simulator-only metadata fields** (these are internal-only and must
  not appear in schema.json)
- Faithfully transcribe enum values, ranges, formats, and patterns from the spec
- Use nested object definitions for complex types (e.g., `Location`)

### 2c — Design db.json

Create seed data that validates against schema.json.

**Structure:**

```json
{
  "restaurants": [
    {
      "id": "rest_001",
      "name": "The Italian Corner",
      "cuisine": "Italian",
      "price_tier": 2,
      "rating": 4.5,
      "location": {
        "latitude": 42.3601,
        "longitude": -71.0589,
        "address": "123 Hanover St",
        "city": "Boston",
        "state": "MA",
        "postal_code": "02108",
        "country": "USA"
      },
      "phone": "+1-555-987-6543",
      "description": "Authentic Italian cuisine in the heart of Boston",
      "accepts_reservations": true
    }
  ],
  "reservations": []
}
```

**Rules:**

- Keys match the top-level `properties` keys in schema.json (store names)
- All seed entities must include all `required` fields from their schema
- Use stable, deterministic IDs (e.g., `rest_001`, `reservation_seed_001`)
- Provide enough linked data for common read-then-write flows (e.g., seed
  restaurants before reservations can be made)
- Use placeholder dates for temporal fields (e.g., `"2025-03-15T19:00:00"`)
  with a note in SKILL.md that the runtime will normalize them
- Ensure referential integrity (foreign keys must reference existing entities)

---

## Step 3 — Write the three outputs

### 3a — SKILL.md structure

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

One subsection per store. For each, list:

- **Primary key:** `<field>`
- **Secondary indexes:** `<field>` (case-insensitive), ...
- **Simulator-only metadata:** `<field>`, `<field>`, ...
- **Write operations:** `<operation>`, `<operation>`, ...
- **Read operations:** `<operation>`, `<operation>`, ...
- **Internal-only (never in responses):** `<field>`, `<field>`, ...

**Add this line at the start of the section:**

```markdown
Entity field definitions: see [`schema.json`](schema.json).
```

**Do NOT list field names and types** — those are in schema.json. Only list
the metadata above (keys, indexes, operations, internal-only flags).

#### Seed Data and Data Generation

**Add this line at the start of the section:**

```markdown
Seed entities are defined in [`db.json`](db.json). Initialize all stores from
db.json on first use of any operation. Shift `date_time` and `created_at`
fields in seed reservations to be in the current session year while maintaining
their relative ordering.
```

**Do NOT list seed entity values** — those are in db.json.

Then provide dynamic generation rules:

- **On-Demand Generation Rules**: when to generate new entities (e.g., "if city
  not found, generate 6–12 restaurants")
- **Availability Generation Rules**: how to generate time slots, profiles, etc.
- **ID Generation Rules**: format for generated IDs (e.g., `rest_gen_<uuid>`)
- **Naming patterns**: how to generate realistic names, descriptions, etc.

Anchor temporal values: "use dates consistent with the current session year."

#### Schema Reference

Replace the detailed schema listings with a single line:

```markdown
Entity schemas are defined in [`schema.json`](schema.json).
```

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

### 3b — schema.json structure

The schema.json output must be a valid JSON Schema (Draft 2020-12) object with:

- `$schema`: `"https://json-schema.org/draft/2020-12/schema"`
- `title`: `"<API Name> Simulator State"`
- `type`: `"object"`
- `required`: array of all store names
- `properties`: one property per store, each an array of entity refs
- `$defs`: one definition per entity type

**Entity schema rules:**

- All entity schemas must have `"additionalProperties": false`
- **All entity schemas must include `"x-primary-key"` annotation** specifying the
  primary key field name (e.g., `"x-primary-key": "id"` or `"x-primary-key": "reservation_id"`).
  This field must be a required string field in the entity schema.
- Include all fields from OpenAPI component schemas
- **Exclude simulator-only metadata fields** (internal-only fields)
- Use correct JSON Schema types: `string`, `number`, `integer`, `boolean`,
  `object`, `array`
- Include `format` where applicable: `date-time`, `email`, `uri`, `uuid`
- Include `enum` arrays for enumerated values
- Include `minimum`, `maximum`, `minLength`, `maxLength`, `pattern` where
  specified
- Use nested object definitions for complex types

### 3c — db.json structure

The db.json output must be a JSON object with:

- Keys matching the top-level `properties` keys in schema.json (store names)
- Values are arrays of seed entities
- All entities must validate against their schema in schema.json

**Seed data rules:**

- Use stable, deterministic IDs (e.g., `rest_001`, not random UUIDs)
- Include all `required` fields from the schema
- Provide enough linked data for common flows (e.g., seed restaurants before
  reservations)
- Use placeholder dates for temporal fields (e.g., `"2025-03-15T19:00:00"`)
- Ensure referential integrity (foreign keys reference existing entities)
- Provide realistic, domain-appropriate values

---

## Step 4 — Self-review before emitting

Walk the generated outputs against this checklist mentally. If any answer is
"no," fix before returning.

**SKILL.md checks:**

- Every path + method in the spec has its own operation section.
- Every required request field is listed for its operation.
- Every response schema has a matching JSON example, and the example is valid
  against the schema.
- Every entity the API can create, read, update, or delete has a store with
  metadata (keys, indexes, operations, internal-only flags).
- Every "When …" error clause is paired with a "Do NOT …" negation.
- Schema-vs-example conflicts in the source spec are called out in the
  affected operation section.
- Empty-result contracts (`[]` vs error) are explicit per list endpoint.
- Idempotency behavior is defined for each write the spec treats as
  idempotent, with a concrete fingerprint.
- The Session State Management section references `schema.json` and does NOT
  list field names/types.
- The Seed Data section references `db.json` and does NOT list seed entity
  values.
- The Schema Reference section is a single line pointing to `schema.json`.
- The file starts with `---` and ends with a markdown line, with no
  surrounding commentary.

**schema.json checks:**

- Every entity type referenced in SKILL.md has a `$defs` entry.
- Every store property in the top-level `properties` matches a store name from
  SKILL.md.
- All entity schemas have `"additionalProperties": false`.
- **All entity schemas have `"x-primary-key"` annotation** specifying the primary
  key field name, and that field is required and of type string.
- Simulator-only metadata fields are absent from all entity schemas.
- All `required` fields from OpenAPI component schemas are marked as required.
- Enum values, formats, and constraints are faithfully transcribed.

**db.json checks:**

- Every key matches a store property name from schema.json.
- Every seed entity includes all `required` fields from its schema.
- All seed entities validate against their schema (run mental validation).
- Referential integrity is maintained (foreign keys reference existing
  entities).
- IDs are stable and deterministic (no random UUIDs).

**Cross-file consistency:**

- Store names are consistent across all three files.
- Entity type names in SKILL.md match `$defs` keys in schema.json.
- Seed data in db.json conforms to schemas in schema.json.

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

## Anti-patterns (do not produce these)

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
- Wrapping the SKILL.md in a code fence, or adding a "Here is the generated
  file:" preamble. The `skill_md` field is the entire content.
- Including simulator-only metadata fields in schema.json. These are
  internal-only and must never appear in the schema.
- Listing field names/types in SKILL.md's Session State Management section.
  Those belong in schema.json.
- Listing seed entity values in SKILL.md's Seed Data section. Those belong in
  db.json.