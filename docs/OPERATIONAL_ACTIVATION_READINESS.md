# Operational Activation Readiness

This is a post-roadmap operational checkpoint, not a new numbered implementation phase. Phases 1–17 remain complete. The purpose is to provide a deliberately manual, fail-closed path for validating production configuration and, only with explicit confirmation, running one bounded monitor-to-ingestion cycle.

## Non-negotiable boundaries

- There is no `schedule` or `cron` trigger.
- The workflow is `workflow_dispatch` only.
- Readiness runs with monitoring, auto-ingestion, and trust promotion all disabled.
- A one-shot cycle temporarily enables monitoring and auto-ingestion only for that job step.
- Trust promotion is always forced off.
- Exactly one queue item may be processed per one-shot cycle.
- Source allow-lists, exact-byte preflight, capacity checks, retry/backoff, and post-write reconciliation remain unchanged.
- Storage pressure pauses ingestion; it never justifies deleting evidence, provenance, history, or validation.

The manual workflow is `.github/workflows/operational-readiness.yml`.

## Required GitHub Actions configuration

The workflow never prints secret values. Before it can be run, configure these repository Actions secrets: `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`.

Configure these Actions variables: `S3_BUCKET`, `S3_REGION`, `MONITOR_SUPABASE_MAX_MB`, `MONITOR_B2_MAX_MB`, `MONITOR_QDRANT_MAX_POINTS`, and `MONITOR_CAPACITY_LOW_WATERMARK_PERCENT`.

The currently validated operator ceilings are 400 MiB for Supabase, 8192 MiB for Backblaze B2, 100000 Qdrant points, and a 10% low-watermark. They must not be increased merely to hide an unexpected growth problem; storage growth should first be measured and explained.

## Manual modes

`readiness` runs the Phase 17 production-readiness audit only. Any missing configuration, unsafe/unknown capacity, broken evidence hash, queue inconsistency, vector mismatch, quality-state problem, or trust event prevents a pass.

`one-shot` first requires the same read-only readiness pass. It then requires the exact confirmation text `RUN-ONE-BOUNDED-CYCLE` and invokes the already validated integrated cycle with `--processing-limit 1`. A not-due monitor performs no source/write work; a due run may commit bounded monitor metadata and at most one exact-preflighted evidence item.

No recurring activation should be added until repeated manual operational runs are reviewed and a separate deployment decision explicitly approves scheduling.
