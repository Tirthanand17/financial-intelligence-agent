# Phase 12 — Auto-Ingest Gate Canary

Phase 12 validates the real `SOURCE_AUTO_INGEST_ENABLED` runtime gate for exactly one already-discovered pending source item.

## Required runtime state

The canary requires, for this process only:

- `SOURCE_MONITORING_ENABLED=true`
- `SOURCE_AUTO_INGEST_ENABLED=true`
- `TRUST_PROMOTION_ENABLED=false`
- all configured cloud-capacity checks in the safe state
- explicit `--allow-network` and `--allow-write` consent

The intended operator command sets the two enabled gates as temporary environment variables. It does not require changing `.env`.

## Write boundary

The canary may process exactly one pending discovery already present in the queue. It must:

1. select one exact pending row;
2. download that source once through the trusted downloader;
3. fully preflight the exact downloaded bytes in memory;
4. persist those same bytes without a second source download;
5. revalidate the queued URL through the normal processor path;
6. reconcile queue status, linked document SHA-256, PostgreSQL deltas, Backblaze B2 bytes, Qdrant points, and post-write capacity.

For a new document, B2 growth must equal the exact preflighted byte count and Qdrant growth must equal the exact preflighted chunk count. For a duplicate document, neither B2 nor Qdrant may grow.

## Safety boundaries

- only one pending queue item may be selected;
- no trust event may be created because `TRUST_PROMOTION_ENABLED=false`;
- no recurring scheduler is enabled by this phase;
- no generic crawler or source-policy bypass is introduced;
- a post-write mismatch is reported as `RECONCILIATION-REQUIRED`; evidence is preserved rather than silently deleted;
- this phase performs research-evidence ingestion only and does not authorize trading actions.

Passing Phase 12 proves the independent auto-ingestion gate can safely process one bounded queue item through the existing trusted ingestion pipeline. A later phase is required before recurring monitoring and recurring ingestion are connected together.
