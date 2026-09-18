# Document Evidence Detail

## Purpose

The Document Evidence Detail surface provides one bounded, read-only view of a single already-indexed document and the structured intelligence derived from it. It is an operator/audit feature only; it does not ingest, refetch, repair, mutate, delete, verify, or promote anything.

## Protected routes

- `GET /dashboard/document` — document lookup page.
- `GET /dashboard/document/{document_id}` — same page with the document ID pre-selected.
- `GET /dashboard/document/{document_id}/status` — authenticated JSON detail snapshot.

All routes reuse the private dashboard HTTP Basic authentication and existing security-header middleware. The JSON route is explicitly `Cache-Control: no-store`.

## Included provenance

For the indexed document the view exposes:

- document ID;
- trusted source ID and source name;
- original and final public source URLs;
- title and content type;
- SHA-256 digest of the exact accepted evidence bytes;
- retrieval timestamp;
- indexed chunk count;
- document status;
- whether a private raw evidence object is retained;
- linked source-monitor discovery records.

The internal B2/S3 object key is deliberately **not** returned. The dashboard states that raw evidence is retained and that the internal object reference is redacted. This preserves operator provenance without exposing storage topology.

## Structured claim audit history

For claims originating from the document the view includes:

- entity, original source metric, exact-alias canonical metric overlay, value and unit;
- publication/effective dates exactly as persisted;
- current claim state and confidence;
- extraction chunk index and source evidence text;
- claim-quality result and rejection reason when applicable;
- canonical entity attribution and attribution basis;
- append-only verification events;
- append-only trust events;
- supersession edges in both directions.

Missing dates remain missing. Retrieval timestamps are never converted into publication or effective dates.

## Bounds

The detail service is deliberately bounded:

- document ID length: 1–128 characters;
- at most 1,000 claims loaded for one document;
- at most 100 discovery links;
- at most 5,000 verification events;
- at most 5,000 trust events.

These are defensive read bounds, not evidence-retention limits. They do not delete or alter persisted history.

## Safety invariants

- read-only;
- no network crawling;
- no raw-object download;
- no provider credentials;
- no object-store keys;
- no claim-state mutation;
- no verification/trust transition;
- no trust-promotion enablement;
- no evidence deletion or repair;
- no scheduler or ingestion change;
- no forecast or trading signal.

## Production validation

The generic `/dashboard/document` entry page is included in `scripts/production_smoke.py`, so production smoke validation requires the page to remain private and retain the same no-store/browser-security contract as the rest of the dashboard workspace.
