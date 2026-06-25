---
name: restaurant-reservation-api
description: Simulate the Restaurant Reservation API by intercepting tool calls and generating realistic, consistent mock responses.
---

# Restaurant Reservation API Simulation

Simulate restaurant search, availability lookup, reservation placement, cancellation, and reservation listing with strict schema compliance and persistent session state.

## Core Principles

- Consistency across the session is paramount.
- Return only fields defined in the response schema, with correct JSON types.
- Generate realistic, domain-appropriate restaurant, availability, and reservation data.
- Maintain referential integrity between reservations, cancellation receipts, and restaurants.
- Return errors only when their specific triggering condition is met.
- For `oneOf` success-or-error responses, return either the success shape or the exact `Error` shape, never a mixed object.

## Session State Management

Entity field definitions: see [`schema.json`](schema.json).

### `restaurants` store
- **Primary key:** `id`
- **Secondary indexes:** `location.city` (case-insensitive), `cuisine` (case-insensitive), `price_tier`, `accepts_reservations`
- **Simulator-only metadata:** distance-from-center profile, availability profile, generated flag
- **Write operations:** `searchRestaurants` (on-demand generation only)
- **Read operations:** `searchRestaurants`, `checkAvailability`, `placeReservation`, `cancelReservation`, `listReservations`
- **Internal-only (never in responses):** distance-from-center profile, availability profile, generated flag

### `reservations` store
- **Primary key:** `id`
- **Secondary indexes:** `guest_email` (case-insensitive), `guest_phone`, `restaurant_id`, `confirmation_code`
- **Simulator-only metadata:** idempotency fingerprint, normalized user identifiers
- **Write operations:** `placeReservation`
- **Read operations:** `placeReservation`, `cancelReservation`, `listReservations`
- **Internal-only (never in responses):** idempotency fingerprint, normalized user identifiers

### `cancellations` store
- **Primary key:** `reservation_id`
- **Secondary indexes:** `restaurant_name` (case-insensitive)
- **Simulator-only metadata:** original reservation fingerprint
- **Write operations:** `cancelReservation`
- **Read operations:** `cancelReservation`
- **Internal-only (never in responses):** original reservation fingerprint

### Idempotency maps
- **Reservation placement fingerprint:** ordered fields `restaurant_id + date_time + party_size + name + phone + email + notes`
- Normalize missing optional `notes` to empty string before fingerprinting.
- Duplicate `placeReservation` calls with the same fingerprint must return the already-stored reservation unchanged and must not create a second reservation.
- `cancelReservation` is destructive and idempotent-by-error: after the first successful cancellation, later calls for the same `reservation_id` must return the exact `Error` shape instead of a second success receipt.

## Seed Data and Data Generation

Seed entities are defined in [`db.json`](db.json). Initialize all stores from
db.json on first use of any operation. Shift `date_time` and `created_at`
fields in seed reservations to be in the current session year while maintaining
their relative ordering.

- **On-Demand Generation Rules:**
  - If `searchRestaurants` is called for a city not present in the `restaurants` store, generate 6-12 restaurants for that city and persist them in `restaurants`.
  - If a city exists but filters produce no matches, return `[]`; do not generate more restaurants just to satisfy the filter.
- **Availability Generation Rules:**
  - `checkAvailability` does not persist slots; generate them deterministically from `restaurant_id`, requested date, and `party_size`.
  - Generate 5-9 slots on the same calendar date, typically between 17:00 and 21:30 local time, in 30-minute increments.
  - Include only slots where `available` is `true`; if none are available, return `[]`.
  - `max_party_size` should usually be between 2 and 10 and must be at least 1.
- **ID Generation Rules:**
  - Generated restaurants: `rest_gen_<cityslug>_<3-digit-sequence>`
  - New reservations: `reservation_<6-digit-sequence>`
  - Confirmation codes: `CONF-<6 uppercase alphanumeric characters>`
  - Cancellation receipts reuse the reservation's `reservation_id` as their primary key.
- **Naming patterns:**
  - Restaurant names should match cuisine and city context, such as neighborhood bistro, grill, kitchen, tavern, house, or table naming styles.
  - Restaurant descriptions should be short, plausible, and cuisine-specific.
  - Use dates and times consistent with the current session year.

## Schema Reference

Entity schemas are defined in [`schema.json`](schema.json).

## API Operation Simulation

### `/search_restaurants` POST

**Operation ID:** `searchRestaurants`
**Tool name (MCP):** `search_restaurants`
**Purpose:** Search for restaurants matching the given criteria with optional filters for cuisine, date/time, party size, price tier, and distance.

**Input Parameters:**
- `city` (required, string) — City name to search in
- `cuisine` (optional, string) — Optional cuisine type filter
- `date_time` (optional, string, date-time) — Optional ISO 8601 datetime for availability-aware search
- `party_size` (optional, integer, minimum 1) — Optional number of guests for filtering
- `price_tier` (optional, integer, minimum 1, maximum 4) — Optional price tier
- `distance_km` (optional, number, minimum 0) — Optional maximum distance from city center in kilometers

**Response Generation:**
1. Validate that `city` is present.
2. Validate `party_size >= 1` when `party_size` is provided.
3. Validate `price_tier` is between 1 and 4 inclusive when provided.
4. Validate `distance_km >= 0` when provided.
5. If no restaurants exist yet for the requested city (case-insensitive match on `location.city`), generate 6-12 restaurants for that city and persist them in `restaurants`.
6. Filter restaurants by `location.city` case-insensitively.
7. If `cuisine` is provided, filter by exact cuisine string case-insensitively.
8. If `price_tier` is provided, filter by exact integer match.
9. If `distance_km` is provided, include only restaurants whose internal distance-from-center profile is less than or equal to `distance_km`.
10. If `party_size` is provided, prefer restaurants that accept reservations; do not exclude a restaurant solely because `party_size` is large unless its internal availability profile makes it implausible.
11. Ignore `date_time` for response shape purposes; it may influence internal ranking only.
12. Sort deterministically by rating descending, then price tier ascending, then `id` ascending.
13. Return a JSON array of `Restaurant` objects. If no restaurants match after filtering, return `[]`.

**State Changes:**
- May append generated `Restaurant` entities to `restaurants` keyed by `id`
- No changes to `reservations`
- No changes to `cancellations`

**Example Response:**
```json
[
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
  },
  {
    "id": "rest_002",
    "name": "Harbor Sushi Bar",
    "cuisine": "Japanese",
    "price_tier": 3,
    "rating": 4.7,
    "location": {
      "latitude": 42.3572,
      "longitude": -71.0517,
      "address": "88 Atlantic Ave",
      "city": "Boston",
      "state": "MA",
      "postal_code": "02110",
      "country": "USA"
    },
    "phone": "+1-555-222-3344",
    "description": "Modern sushi and omakase near the waterfront",
    "accepts_reservations": true
  }
]
```

### `/check_availability` POST

**Operation ID:** `checkAvailability`
**Tool name (MCP):** `check_availability`
**Purpose:** Check availability for a specific restaurant on a given date and time for a party size.

**Input Parameters:**
- `restaurant_id` (required, string) — Unique restaurant identifier
- `date_time` (required, string, date-time) — ISO 8601 datetime for the date to check
- `party_size` (required, integer, minimum 1) — Number of guests in the party

**Response Generation:**
1. Validate that `restaurant_id`, `date_time`, and `party_size` are present.
2. Validate `party_size >= 1`.
3. Look up `restaurant_id` in `restaurants`.
4. If the restaurant does not exist, return the exact `Error` shape.
5. If the restaurant exists but `accepts_reservations` is `false`, return `[]`.
6. Generate deterministic same-day availability slots around the requested time.
7. Exclude slots where `available` would be `false`; return only available slots.
8. Ensure every returned item matches the `AvailabilitySlot` schema exactly.
9. If no slots are available, return `[]`.

**State Changes:**
- None

**Example Response:**
```json
[
  {
    "time": "2025-03-15T18:00:00",
    "max_party_size": 4,
    "available": true
  },
  {
    "time": "2025-03-15T18:30:00",
    "max_party_size": 6,
    "available": true
  },
  {
    "time": "2025-03-15T19:30:00",
    "max_party_size": 8,
    "available": true
  }
]
```

### `/place_reservation` POST

**Operation ID:** `placeReservation`
**Tool name (MCP):** `place_reservation`
**Purpose:** Place a reservation at a restaurant with idempotent duplicate handling.

**Input Parameters:**
- `restaurant_id` (required, string) — Unique restaurant identifier
- `date_time` (required, string, date-time) — ISO 8601 datetime for the reservation
- `party_size` (required, integer, minimum 1) — Number of guests
- `name` (required, string) — Guest's full name
- `phone` (required, string) — Guest's contact phone number
- `email` (required, string, email) — Guest's email address
- `notes` (optional, string) — Optional special requests or dietary restrictions

**Response Generation:**
1. Validate that `restaurant_id`, `date_time`, `party_size`, `name`, `phone`, and `email` are present.
2. Validate `party_size >= 1`.
3. Validate `email` is a syntactically valid email string.
4. Look up `restaurant_id` in `restaurants`.
5. If the restaurant does not exist, return the exact `Error` shape.
6. Build the idempotency fingerprint from `restaurant_id + date_time + party_size + name + phone + email + notes`, normalizing missing `notes` to empty string.
7. If a reservation with the same fingerprint already exists in `reservations`, return that stored `Reservation` unchanged.
8. If the restaurant exists but `accepts_reservations` is `false`, return the exact `Error` shape.
9. Generate a new reservation with a stable new `id`, copy `restaurant_name` from the restaurant, set `guest_name` from `name`, `guest_phone` from `phone`, `guest_email` from `email`, generate `confirmation_code`, and set `created_at` to the current session timestamp.
10. If `notes` is omitted, omit `notes` from the response object.
11. If `status` is included, it must be the string `confirmed`.
12. Persist the new reservation in `reservations`.
13. Return the full `Reservation` object.

**State Changes:**
- Append a new `Reservation` entity to `reservations` keyed by `id` unless the idempotency fingerprint already exists
- No changes to `restaurants`
- No changes to `cancellations`

**Example Response:**
```json
{
  "id": "reservation_000101",
  "restaurant_id": "rest_001",
  "restaurant_name": "The Italian Corner",
  "date_time": "2025-03-15T19:00:00",
  "party_size": 4,
  "guest_name": "John Doe",
  "guest_phone": "+1-555-123-4567",
  "guest_email": "john.doe@example.com",
  "notes": "Window seat preferred, vegetarian options needed",
  "status": "confirmed",
  "confirmation_code": "CONF-A1B2C3",
  "created_at": "2025-03-10T14:30:00"
}
```

### `/cancel_reservation` POST

**Operation ID:** `cancelReservation`
**Tool name (MCP):** `cancel_reservation`
**Purpose:** Cancel an existing reservation and return a cancellation receipt.

**Input Parameters:**
- `reservation_id` (required, string) — Unique reservation identifier
- `reason` (optional, string) — Optional reason for cancellation

**Response Generation:**
1. Validate that `reservation_id` is present.
2. Look up `reservation_id` in `reservations`.
3. If an active reservation with that `reservation_id` exists, create a `CancellationReceipt` using the reservation's `id`, `restaurant_name`, and `date_time`, set `cancelled_at` to the current session timestamp, copy `reason` if provided, and set `refund_policy` to `No charge for cancellations` unless another value is already stored.
4. Persist the receipt in `cancellations` keyed by `reservation_id`.
5. Remove the reservation from `reservations` so later `listReservations` calls no longer show it.
6. Return the `CancellationReceipt`.
7. If no active reservation exists but a cancellation receipt with that `reservation_id` already exists in `cancellations`, return the exact `Error` shape indicating the reservation was not found or was already cancelled.
8. If neither an active reservation nor a stored cancellation receipt exists, return the exact `Error` shape.

**State Changes:**
- Remove the matching `Reservation` entity from `reservations`
- Append a new `CancellationReceipt` entity to `cancellations` keyed by `reservation_id` on first successful cancellation
- No changes to `restaurants`

**Example Response:**
```json
{
  "reservation_id": "reservation_000101",
  "restaurant_name": "The Italian Corner",
  "original_date_time": "2025-03-15T19:00:00",
  "cancelled_at": "2025-03-12T10:15:00",
  "reason": "Change of plans",
  "refund_policy": "No charge for cancellations"
}
```

### `/list_reservations` POST

**Operation ID:** `listReservations`
**Tool name (MCP):** `list_reservations`
**Purpose:** List all reservations for a user identified by email address or phone number.

**Input Parameters:**
- `user_id` (required, string) — User identifier, either email address or phone number

**Response Generation:**
1. Validate that `user_id` is present.
2. Normalize `user_id` for matching: compare case-insensitively against `guest_email`; compare exact string against `guest_phone`.
3. Read all active reservations from `reservations` where `guest_email` matches normalized email or `guest_phone` matches the exact phone string.
4. Sort results deterministically by `date_time` ascending, then `id` ascending.
5. Return a JSON array of `Reservation` objects.
6. If no reservations match, return `[]`.

**State Changes:**
- None

**Example Response:**
```json
[
  {
    "id": "reservation_seed_001",
    "restaurant_id": "rest_001",
    "restaurant_name": "The Italian Corner",
    "date_time": "2025-03-15T19:00:00",
    "party_size": 2,
    "guest_name": "John Doe",
    "guest_phone": "+1-555-123-4567",
    "guest_email": "john.doe@example.com",
    "notes": "Anniversary dinner",
    "status": "confirmed",
    "confirmation_code": "CONF-SEED01",
    "created_at": "2025-03-10T14:30:00"
  },
  {
    "id": "reservation_seed_002",
    "restaurant_id": "rest_002",
    "restaurant_name": "Harbor Sushi Bar",
    "date_time": "2025-03-20T18:30:00",
    "party_size": 4,
    "guest_name": "John Doe",
    "guest_phone": "+1-555-123-4567",
    "guest_email": "john.doe@example.com",
    "status": "confirmed",
    "confirmation_code": "CONF-SEED02",
    "created_at": "2025-03-11T09:15:00"
  }
]
```

## Error Handling

Exact error schema:

```json
{
  "error": "string"
}
```

Allowed error conditions:

- **When** a required request field for an operation is missing.
  - Return:
    ```json
    {
      "error": "Missing required field: <field_name>"
    }
    ```
  - Do **NOT** return this error if all required fields for that operation are present.

- **When** a numeric constraint from the request schema is violated (`party_size < 1`, `price_tier < 1`, `price_tier > 4`, or `distance_km < 0`).
  - Return:
    ```json
    {
      "error": "Invalid request parameters"
    }
    ```
  - Do **NOT** return this error if all provided numeric values satisfy the documented constraints.

- **When** an email field is required to be email-formatted and the provided value is not a syntactically valid email string.
  - Return:
    ```json
    {
      "error": "Invalid request parameters"
    }
    ```
  - Do **NOT** return this error if the email is syntactically valid.

- **When** a referenced restaurant does not exist for `checkAvailability` or `placeReservation`.
  - Return:
    ```json
    {
      "error": "Restaurant not found"
    }
    ```
  - Do **NOT** return this error if the `restaurant_id` exists in `restaurants`.

- **When** `placeReservation` targets a restaurant that exists but does not accept reservations.
  - Return:
    ```json
    {
      "error": "Restaurant does not accept reservations"
    }
    ```
  - Do **NOT** return this error if the restaurant exists and `accepts_reservations` is `true`.

- **When** `cancelReservation` is called for a reservation that is not active because it never existed or was already cancelled.
  - Return:
    ```json
    {
      "error": "Reservation not found"
    }
    ```
  - Do **NOT** return this error if the reservation currently exists in `reservations` and has not yet been cancelled.

### Endpoint-specific error applicability

#### `/search_restaurants` POST
- Missing required field errors apply to `city`.
- Numeric constraint errors apply to `party_size`, `price_tier`, and `distance_km` when provided.
- No restaurant-not-found error applies.
- No results must return `[]`, not an error.

#### `/check_availability` POST
- Missing required field errors apply to `restaurant_id`, `date_time`, and `party_size`.
- Numeric constraint errors apply to `party_size`.
- Restaurant-not-found error applies when `restaurant_id` is absent from `restaurants`.
- No results must return `[]`, not an error.

#### `/place_reservation` POST
- Missing required field errors apply to `restaurant_id`, `date_time`, `party_size`, `name`, `phone`, and `email`.
- Numeric constraint errors apply to `party_size`.
- Email-format error applies to `email`.
- Restaurant-not-found error applies when `restaurant_id` is absent from `restaurants`.
- Restaurant-does-not-accept-reservations error applies only when the restaurant exists and `accepts_reservations` is `false`.
- Duplicate idempotent requests must return the existing `Reservation`, not an error.

#### `/cancel_reservation` POST
- Missing required field errors apply to `reservation_id`.
- Reservation-not-found error applies when the reservation is absent from active `reservations`, including after a prior successful cancellation.

#### `/list_reservations` POST
- Missing required field errors apply to `user_id`.
- No results must return `[]`, not an error.

Additional rules:
- Return only the `error` field for errors.
- Do not add status codes, error codes, stack traces, `details`, or any extra keys.

## Realism Guidelines

- Ratings should usually fall between 3.8 and 4.9 for generated restaurants.
- `price_tier` should be an integer from 1 to 4 and should correlate loosely with cuisine and neighborhood style.
- Boston-area seed and generated restaurants should use plausible MA addresses and phone numbers in `+1-555-...` format.
- Availability should cluster around lunch and dinner service, with dinner slots more common between 17:00 and 21:30.
- `created_at` must be less than or equal to the reservation's `date_time`.
- `cancelled_at` must be greater than or equal to the original reservation's `created_at` when that reservation existed in-session.
- Confirmation codes should look human-readable and stable once assigned.
- Guest names, emails, and phone numbers must be reused exactly from stored reservations when those reservations are returned later.

## Response Format

Return only valid JSON matching the selected response schema. No markdown, no prose, no HTTP envelope, no extra keys. For each operation, return either the success JSON shape or the exact `{"error":"..."}` object.

## Consistency Checklist

- Did you match the called tool to the correct operation?
- Did you validate only the fields and constraints explicitly required by the spec?
- Did you avoid returning any field not defined in the response schema?
- Did you preserve JSON types exactly (`integer` vs `number`, `boolean`, `string`, `array`, `object`)?
- Did you reuse existing restaurant and reservation IDs instead of generating new ones for existing entities?
- Did you persist newly created reservations so later reads return the same values?
- Did you remove cancelled reservations from active `reservations` after a successful cancellation?
- Did you persist cancellation receipts so repeated cancellation attempts return the correct error behavior?
- Did you maintain referential integrity between `reservation.restaurant_id` and `restaurants.id`?
- Did you return `[]` for empty list results instead of an error where required?
- Did you apply the reservation idempotency fingerprint exactly and return the stored reservation on duplicates?
- Did you keep temporal fields internally consistent (`created_at <= date_time`, `cancelled_at >= created_at` when applicable)?
- Did you sort list results deterministically?
- Did you return an error only when its exact triggering condition was met?
- Did you keep error objects to exactly one field: `error`?

## Validation Coverage

Covered operations:
- `/search_restaurants` POST
- `/check_availability` POST
- `/place_reservation` POST
- `/cancel_reservation` POST
- `/list_reservations` POST

Tracked entities and relationships:
- `Restaurant`
- `Reservation` -> references `Restaurant` by `restaurant_id`
- `CancellationReceipt` -> references cancelled `Reservation` by `reservation_id` and carries `restaurant_name` from the original reservation