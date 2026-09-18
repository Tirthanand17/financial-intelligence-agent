# Read-Only Evidence Export

## Purpose

This post-roadmap feature provides bounded operator exports of already-persisted structured claim evidence. It does not fetch new sources, mutate claim state, change trust, alter scheduler behavior, repair stores, or delete evidence.

## Protected surfaces

All export surfaces reuse the private dashboard HTTP Basic authentication boundary.

- `GET /dashboard/export` — filter-and-download operator page.
- `GET /api/v1/export/claims.json` — JSON attachment.
- `GET /api/v1/export/claims.csv` — CSV attachment.

Responses are explicitly `Cache-Control: no-store`. There are no POST, PUT, PATCH, or DELETE export routes.

## Bounded query contract

Supported filters are the same persisted-evidence semantics used by Evidence Search:

- free text `q`;
- exact `source_id`;
- exact claim `state`;
- literal case-insensitive `entity` and `metric` matching;
- `date_from` / `date_to` using persisted effective date when present, otherwise persisted publication date;
- `limit`, maximum 100 rows per request;
- `offset`, maximum 5000.

Missing publication/effective dates remain missing. Retrieval time is not substituted as an evidence date.

## Exported provenance

The claim export contains safe provenance fields needed to trace evidence, including source URL, document ID, document title/source, SHA-256 digest, content type, retrieval timestamp, persisted dates, claim state, quality diagnostics, canonical indicator overlay, and an evidence excerpt.

The export deliberately does **not** expose private B2/S3 object keys, storage credentials, database credentials, Qdrant credentials, dashboard credentials, raw environment values, or any secret configuration.

## CSV behavior

CSV uses a fixed field order and Python's standard CSV quoting rules. Text containing commas or quotation marks is escaped by the CSV writer rather than manually concatenated.

## Safety boundary

The export layer is a projection of existing stored evidence only. It cannot:

- ingest or crawl sources;
- promote or alter claim/trust state;
- enable trust promotion;
- modify evidence, documents, vectors, queue rows, monitoring state, or cloud storage;
- expose private storage object references;
- invent publication/effective dates;
- produce trading actions, market forecasts, or autonomous financial execution.

For datasets larger than one bounded response, an operator must page explicitly using filters and `offset`; the service does not silently lift the maximum or dump the entire database into memory.
