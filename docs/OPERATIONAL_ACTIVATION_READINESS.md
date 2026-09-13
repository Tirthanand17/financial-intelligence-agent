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

## Completed operational validation — 2026-09-13

The repository Actions configuration was validated successfully and the read-only readiness workflow passed with all global runtime gates disabled. Bounded one-shot operational validation was then completed for all four registered India Authority-A monitors: RBI, SEBI, NSE, and MoSPI.

Each one-shot was limited to one queue item and kept `TRUST_PROMOTION_ENABLED=false`. RBI, SEBI, and NSE passed directly. The first MoSPI Actions attempt failed closed before any evidence write because the integrated canary used the generic GET document downloader for a source whose approved latest-releases endpoint requires the source-specific POST adapter. That wiring defect was fixed in PR #21 by routing the integrated monitor stage through `download_monitor_payload`, with regression coverage. The corrected live MoSPI cycle then passed and ingested exactly one evidence item.

The final post-write read-only audit reported:

- 15 evidence documents;
- 40 claims;
- 41 expected Qdrant points and 41 actual Qdrant points;
- 0 evidence-integrity failures;
- 0 queue metadata or linked-document anomalies;
- 0 orphan claims;
- 0 quality-failed VERIFIED/TRUSTED claims;
- 0 trust events;
- all 4 required monitors ready; and
- safe measured cloud capacity under the approved ceilings.

The full regression suite after the MoSPI source-wiring fix passed with `348 passed, 2 warnings`; the warnings are the existing Starlette/httpx and AnyIO deprecations.

This completes the bounded manual operational-activation validation. It does **not** authorize recurring unattended scheduling, unrestricted crawling, autonomous financial actions, or automatic trust promotion.

No recurring activation should be added until a separate deployment decision explicitly approves scheduling. Any later scheduler must preserve the same source allow-lists, one-item/bounded processing rules, exact-byte evidence handling, capacity fail-closed behavior, storage-preservation policy, and kill switches.