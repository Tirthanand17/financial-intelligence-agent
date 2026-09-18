# Provenance Graph

## Purpose

The Provenance Graph is a protected read-only evidence-lineage view for one already-indexed document. It converts persisted provenance and append-only audit relationships into explicit nodes and edges without fetching or changing evidence.

## Protected routes

- `GET /dashboard/provenance`
- `GET /dashboard/provenance/{document_id}`
- `GET /dashboard/provenance/{document_id}/status`

The routes reuse dashboard authentication and the existing security-header middleware. JSON is explicitly `Cache-Control: no-store`.

## Graph model

The graph can contain:

- trusted source node;
- source-monitor discovery nodes;
- indexed document node with SHA-256 provenance;
- structured claim nodes;
- canonical entity-attribution nodes;
- verification-event nodes;
- trust-event nodes;
- external claim references when a supersession relationship points outside the selected document.

Relationship types include:

- `published_evidence`;
- `discovered_document`;
- `extracted_claim`;
- `attributed_as`;
- `verification_event`;
- `trust_event`;
- `superseded_by`.

## Evidence boundary

The graph is derived from the existing bounded Document Evidence Detail snapshot. The private B2/S3 object key is not returned. The document node includes only safe provenance such as SHA-256, content type, retrieval timestamp, chunk count, status, and whether raw evidence is retained.

Missing publication/effective dates remain missing. No inference or retrieval timestamp substitution is performed.

## Safety

- read-only;
- no network crawling;
- no raw evidence download;
- no storage-object key exposure;
- no provider credentials;
- no claim-state mutation;
- no verification/trust event creation;
- no automatic trust promotion;
- no evidence repair, rewrite, or deletion;
- no ingestion/scheduler change;
- no forecast or trading action.

The graph is an audit visualization only; it does not create new provenance relationships in persistence.
