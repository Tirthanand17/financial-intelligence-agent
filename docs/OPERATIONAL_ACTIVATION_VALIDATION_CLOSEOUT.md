# Operational Activation Validation Closeout

Date: 2026-09-13

Status: **COMPLETE — bounded manual validation only**

This record closes the post-roadmap operational-activation validation checkpoint. It does not create a new numbered implementation phase and does not enable unattended production scheduling.

## What was validated

- GitHub Actions cloud configuration was present and usable without exposing secret values.
- Read-only production readiness passed with monitoring, auto-ingestion, and trust promotion disabled.
- Bounded one-shot monitor-to-ingestion validation completed for RBI, SEBI, NSE, and MoSPI.
- Every one-shot retained the `--processing-limit 1` bound and `TRUST_PROMOTION_ENABLED=false`.
- Source allow-lists, publication-date safety, exact-byte preflight, queue linkage, PostgreSQL/B2/Qdrant reconciliation, and storage-capacity checks remained enforced.

## Source results

| Monitor | Result | Operational effect |
| --- | --- | --- |
| `rbi-press-releases-rss` | PASS | one bounded evidence item processed; no trust event |
| `sebi-rss` | PASS | one bounded evidence item processed; no trust event |
| `nse-daily-buyback-rss` | PASS | one bounded evidence item processed; three candidate claims created; no trust event |
| `mospi-latest-releases-api` | PASS after source-wiring fix | one bounded evidence item processed; no trust event |

## MoSPI fail-closed incident and remediation

The first MoSPI Actions one-shot stopped before evidence ingestion with `BLOCKED-DUE` because the integrated canary called the generic trusted-document GET downloader against the approved MoSPI latest-releases API, which is POST-based. No partial evidence write occurred.

The operational path was corrected to use `app.monitoring.runner.download_monitor_payload`, the same source-specific dispatcher used by the monitor runner. The change preserves generic GET behavior for RBI/SEBI/NSE and uses the approved MoSPI POST adapter only for MoSPI. Regression coverage was added to prevent the integrated cycle from reverting to the generic GET path.

The fix was validated by the full suite (`348 passed, 2 warnings`), a live corrected MoSPI bounded one-shot (`PASS-COMMITTED`), and a final read-only cross-store audit.

## Final audited state

- Evidence documents: **15**
- Claims: **40**
- Qdrant points: **41 expected / 41 actual**
- Evidence integrity failures: **0**
- Queue metadata anomalies: **0**
- Linked-document anomalies: **0**
- Orphan claims: **0**
- Quality-failed VERIFIED/TRUSTED claims: **0**
- Trust events: **0**
- Required monitors ready: **4 / 4**
- India Authority-A monitoring gaps: **0**
- Capacity decision: **safe**

## Storage and safety state

The approved operational ceilings remain 400 MiB Supabase, 8192 MiB Backblaze B2, 100000 Qdrant points, and a 10% low-watermark. Capacity protection is fail-closed. Evidence, provenance, history, validation records, and source coverage must not be deleted or weakened to make room.

Outside an explicitly confirmed bounded one-shot run, the safe runtime defaults remain:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
TRUST_PROMOTION_ENABLED=false
```

## Deployment decision boundary

Manual operational validation is complete. Recurring unattended scheduling is **not approved by this closeout**. A separate deployment decision must define cadence, concurrency, retry behavior, failure notification, kill-switch procedure, storage-growth review, and rollback criteria before any recurring scheduler is enabled.
