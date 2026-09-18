# Protected Read-Only API v1

## Purpose

`/api/v1` is the first stable versioned JSON surface for private evidence inspection. It wraps existing persisted-evidence services without changing their evidence, quality, verification, trust, or storage behavior.

The API is intentionally **read-only**. It does not expose ingestion, scheduler, repair, deletion, claim-state transition, or trust-promotion controls.

## Authentication and cache policy

Every `/api/v1` endpoint reuses the private dashboard HTTP Basic authentication. Missing or invalid credentials fail closed with HTTP 401. The security middleware applies `Cache-Control: no-store` and `Pragma: no-cache` to successful responses and error/authentication responses under `/api/v1`.

The API does not expose provider credentials or private B2/S3 object keys.

## Endpoints

### `GET /api/v1`

Returns API metadata, stable endpoint names, and the read-only safety contract.

### `GET /api/v1/intelligence`

Query parameters:

- `source_id` optional exact source ID;
- `limit` 1–50, default 12.

Organizes already-persisted structured evidence. It does not generate new facts, forecasts, signals, or recommendations.

### `GET /api/v1/evidence/search`

Query parameters:

- `q` optional literal free-text query;
- `source_id` exact source filter;
- `state` exact claim-state filter;
- `entity` literal entity substring;
- `metric` literal metric substring;
- `date_from` / `date_to` ISO dates;
- `limit` 1–100;
- `offset` 0–5000.

Date filtering follows the existing evidence-search contract: `effective_date` when present, otherwise `publication_date`. Retrieval time is never substituted for temporal scope.

### `GET /api/v1/documents/{document_id}`

Returns the bounded Document Evidence Detail snapshot with source/public provenance, SHA-256, discovery linkage, claim/audit history, and redacted private storage topology. Unknown IDs return 404.

### `GET /api/v1/timeline`

Query parameters:

- `entity`, `metric`, `source_id` optional exact filters;
- `series_limit` 1–50;
- `points_per_series` 1–100.

Uses only persisted publication/effective dates. Undated evidence remains undated.

### `GET /api/v1/conflicts`

Query parameters:

- `participant_source_id`;
- `entity_contains`;
- `metric_contains`;
- `limit` 1–100.

Returns exact-comparison independent-source disagreements. It never chooses a winning source/value or changes persisted claim state.

### `GET /api/v1/provenance/{document_id}`

Returns the bounded provenance graph for a document. Unknown IDs return 404. Private object-store keys are not exposed.

### `GET /api/v1/quality/scorecards`

Returns factual completeness/provenance dimensions. There is no composite truth score, source ranking, or automatic trust decision.

## Versioning contract

- Existing legacy routes remain unchanged.
- Breaking response/route changes require a new API version rather than silently repurposing `/api/v1`.
- New backward-compatible read-only fields/endpoints may be added to v1 with tests and documentation.
- No write method is allowed under `/api/v1`; regression tests inspect registered route methods and fail if POST/PUT/PATCH/DELETE appears.

## Non-negotiable safety boundary

The API performs no source crawling, ingestion control, scheduler mutation, evidence deletion, repair, trust promotion, autonomous conflict resolution, forecasting, trading recommendation, or financial execution. It is a private inspection interface over already-persisted evidence and provenance.
