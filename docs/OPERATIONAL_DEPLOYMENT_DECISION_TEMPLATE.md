# Operational Deployment Decision Template

Use this only after bounded manual operational validation is complete. Completing this document is required before enabling any recurring scheduler.

## Decision

- Decision: `NOT YET APPROVED` / `APPROVED`
- Approved by:
- Approval date:
- Intended start date:

## Scheduler scope

- Monitors included:
- Cadence per monitor:
- Maximum queue items per run:
- Concurrency limit:
- Maximum runtime per job:

## Safety controls that must remain unchanged

- Trusted-source allow-lists remain authoritative.
- Exact-byte evidence preflight and SHA reconciliation remain mandatory.
- `TRUST_PROMOTION_ENABLED=false` unless separately validated and approved.
- Capacity checks must run before ingestion and fail closed on unknown/low capacity.
- Evidence, provenance, validation history, and source coverage must not be deleted to save storage.
- A kill switch must be able to stop future scheduled executions without deleting stored evidence.

## Failure and notification policy

Define how failed source requests, repeated retries, queue errors, integrity mismatches, capacity blocks, and external-provider outages are surfaced to the operator. Repeated failures must not silently increase write volume or bypass source policy.

## Storage-growth review

Before approval, record current Supabase, Backblaze B2, and Qdrant usage and estimate bounded growth at the proposed cadence. If provider capacity becomes low or unknown, ingestion must pause and the operator must be informed rather than reducing evidence quality.

## Rollback criteria

Recurring execution must be disabled if any of the following occurs: evidence hash mismatch, queue/document linkage anomaly, Qdrant count mismatch, unexpected trust event, source-policy failure pattern, unexplained storage growth, or any safety invariant regression.

## Approval record

Scheduling must remain absent while the decision is `NOT YET APPROVED`. Changing this record to `APPROVED` is necessary but not sufficient: the scheduler implementation must still pass review, CI, and a read-only readiness check before merge.
