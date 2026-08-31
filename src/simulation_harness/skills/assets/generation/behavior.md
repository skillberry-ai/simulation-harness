You write the global behavior section of an API-simulator SKILL.md. You receive
the API name, its data-model entities (with field names, types, and enums), and
its operations (with kind, summary, and description). Your job is to specify how
the simulator
must COMPUTE and keep CONSISTENT the values it returns — especially numeric
fields — across the whole session. This section is the single source of truth
for numbers; per-operation sections defer to it.

Output ONLY markdown containing EXACTLY these three subsections, in this order,
each as an H3 (`###`) heading with the exact text shown:

### Numeric Ranges and Ordering
- For each numeric field in the data model, give a realistic, domain-appropriate
  value range using concrete integers, plus any ordering constraint between
  related numeric fields (e.g. tiered prices must be strictly ordered).

### Derivation Rules
- For every response value that is COMPUTED rather than copied from the request
  or the store, state the exact formula or relationship as a bullet (e.g. a
  total equals the sum of line-item prices; a change fee is a fixed positive
  integer). Name fields using the entity field names you were given. Every rule
  must be deterministic so repeated calls yield identical values.
- Numeric relationships stated in an operation's `description` are authoritative
  and must appear as Derivation Rules even when no schema field encodes them.

### On-Demand Generation Rules
- State how to deterministically generate any records or numeric fields that are
  not seeded, so regenerating the same logical record yields identical numbers.
  Cover ordering and non-negativity constraints.

Use bullet lists, not prose. Reference only entity field names that appear in
the input; do not invent fields. Do not wrap the whole output in a code fence.
If a `feedback` section is present, the previous attempt was rejected; fix
exactly those problems.
