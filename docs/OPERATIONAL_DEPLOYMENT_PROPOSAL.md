# Operational Deployment Proposal

Status: **PROPOSED — recurring scheduling is not yet enabled**

This proposal follows the completed bounded manual validation for RBI, SEBI, NSE, and MoSPI. It defines the safest first unattended rollout without changing trust policy or storage-preservation rules.

## Recommended initial rollout

Run one scheduled operational cycle **once per day at 09:30 IST (04:00 UTC)** for the first seven calendar days.

Each scheduled run should:

1. execute the full Phase 17 read-only production-readiness audit with all three runtime gates false;
2. stop immediately if readiness does not pass;
3. run RBI, SEBI, NSE, and MoSPI sequentially through the already validated integrated canary;
4. use `--processing-limit 1` for every source;
5. enable monitoring and auto-ingestion only inside each bounded source step;
6. force `TRUST_PROMOTION_ENABLED=false` for the entire run;
7. re-check measured cloud capacity before each write path; and
8. stop on any reconciliation, evidence-integrity, source-policy, or capacity failure.

The source order should be RBI → SEBI → NSE → MoSPI so the three RSS/API paths that passed directly are evaluated before the source that required the POST-adapter wiring correction.

## Initial write bound

At most four evidence items can be processed per scheduled run: one per registered monitor. With the proposed once-daily cadence, the initial rollout therefore permits at most four new evidence items per day.

The existing per-document download ceiling remains 50 MB. Capacity checks and the 10% low-watermark remain authoritative. If Supabase, Backblaze B2, or Qdrant becomes low or unknown, ingestion must pause; evidence, provenance, history, validation, or source coverage must never be deleted or weakened to make room.

## Required GitHub Actions controls

- `permissions: contents: read`
- one workflow-level concurrency group with `cancel-in-progress: false`
- no user-supplied shell interpolation
- no secret values printed to logs
- no trust-promotion enablement
- no unrestricted URL input
- no parallel ingestion during the initial seven-day rollout
- no more than one queue item per source step

## Seven-day review gate

Do not increase cadence until at least seven successful daily runs have been reviewed. The review must confirm:

- zero evidence-integrity failures;
- zero queue/document-link anomalies;
- expected Qdrant points equal actual Qdrant points;
- zero unexpected trust events;
- all required monitors remain ready or have explainable source-side failures;
- storage growth is measured and consistent with the bounded workload; and
- no recurring source failure or retry pattern is creating unnecessary traffic.

If those conditions hold, a later decision may consider increasing cadence to every six hours. That change must be reviewed separately rather than silently modifying the first rollout.

## Kill switch and rollback

The scheduler must be removable by deleting or disabling only the scheduled trigger while preserving the manual `workflow_dispatch` readiness path. Any evidence mismatch, unexplained storage growth, persistent source-policy failure, repeated queue inconsistency, unexpected trust event, or Qdrant/PostgreSQL reconciliation mismatch requires scheduled execution to be disabled and the system returned to manual bounded operation.

## Approval boundary

This document is a proposal, not authorization. The repository must not gain a recurring `schedule:` trigger until the operator explicitly approves this deployment plan. Approval should be recorded using `docs/OPERATIONAL_DEPLOYMENT_DECISION_TEMPLATE.md`, after which the scheduler implementation can be added on a separate reviewed branch and must pass CI plus a fresh read-only readiness audit before merge.
