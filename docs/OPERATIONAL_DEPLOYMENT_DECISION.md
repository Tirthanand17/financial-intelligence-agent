# Operational Deployment Decision

## Decision

- Decision: `APPROVED`
- Approved by: repository operator (`Tirthanand17`)
- Approval date: 2026-09-13
- Intended start date: after scheduler implementation passes CI and final readiness validation

## Scheduler scope

- Monitors included: RBI, SEBI, NSE, MoSPI registered monitors
- Cadence per monitor: once daily at 09:30 IST (04:00 UTC)
- Maximum queue items per run: one per source, four total maximum
- Concurrency limit: one scheduled workflow run at a time
- Maximum runtime per job: 45 minutes

## Safety controls that remain unchanged

- Trusted-source allow-lists remain authoritative.
- Exact-byte evidence preflight and SHA reconciliation remain mandatory.
- `TRUST_PROMOTION_ENABLED=false` remains mandatory.
- Capacity checks run before ingestion and fail closed on unknown/low capacity.
- Evidence, provenance, validation history, and source coverage are never deleted to save storage.
- The kill switch is removal/disablement of the scheduled trigger while preserving manual readiness.

## Failure and notification policy

Any readiness, source-policy, queue, reconciliation, integrity, capacity, or provider failure makes the scheduled GitHub Actions run fail visibly. The workflow stops at the failing step and does not increase processing bounds or bypass controls. GitHub Actions run status is the initial operator-visible failure signal.

## Storage-growth review

Approved ceilings remain 400 MiB Supabase, 8192 MiB Backblaze B2, 100000 Qdrant points, and a 10% low-watermark. The initial schedule permits at most four evidence items per day. If capacity becomes low or unknown, ingestion pauses rather than reducing evidence quality.

## Rollback criteria

Disable recurring execution on any evidence hash mismatch, queue/document linkage anomaly, Qdrant count mismatch, unexpected trust event, repeated source-policy failure, unexplained storage growth, or safety-invariant regression.

## Approval record

Recurring scheduling is approved only for the conservative once-daily seven-day observation rollout described in `docs/OPERATIONAL_DEPLOYMENT_PROPOSAL.md`. Any cadence increase requires a separate review and approval.
