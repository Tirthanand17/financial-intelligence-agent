# Legacy Private API Authentication Hardening

## Purpose

The deployed service is private operational infrastructure. The historical `POST /ingest` and `POST /ask` routes were created before the protected dashboard/API-v1 surfaces and did not explicitly require operator authentication.

This hardening closes that legacy boundary by reusing the existing dashboard operator HTTP Basic authentication for both POST routes.

## Protected routes

- `POST /ingest` — operator-only manual ingestion.
- `POST /ask` — operator-only grounded retrieval over private persisted evidence.

The existing recurring scheduler is not routed through `POST /ingest`; it continues to use bounded internal scripts/services and its existing readiness/gate controls.

## Fail-closed behavior

- missing credentials → HTTP 401 when operator auth is configured;
- invalid credentials → HTTP 401;
- missing server-side dashboard username/password configuration → HTTP 503;
- authentication is checked before either route calls the ingestion or retrieval service;
- valid operator authentication preserves the existing request/response service contracts.

`GET /sources` remains read-only and returns only non-secret registry metadata. `GET /health` remains unchanged.

## Unchanged safety boundaries

This milestone does not:

- alter the scheduled ingestion cadence or source set;
- bypass source URL allow-lists;
- enable trust promotion;
- change claim verification state;
- delete or rewrite evidence;
- alter PostgreSQL, B2, or Qdrant schemas/data by itself;
- add a new credential or expose an existing credential;
- add paid infrastructure;
- introduce forecasting or trading behavior.

The same private dashboard credentials already present in deployment configuration are reused; no secret values are committed to the repository.

## Validation

Regression tests require unauthenticated and invalid-credential requests to fail before service execution, require missing server-side auth configuration to fail closed, verify authenticated requests retain their previous service contracts, and verify the read-only source registry response contains no credential/configuration fields.
