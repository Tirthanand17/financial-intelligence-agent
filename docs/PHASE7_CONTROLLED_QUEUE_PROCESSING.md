# Phase 7 Controlled Queue Processing

Phase 7 moves from discovery-only monitoring toward processing the persisted discovery queue, but it does **not** enable scheduled monitoring, automatic ingestion, or trust promotion yet.

The first Phase 7 checkpoint is deliberately read-only. Before any queued RBI item may be persisted as evidence, the project validates one real pending discovery end to end in memory using the same trusted-source controls as ingestion.

## Safety gates remain off

Normal runtime settings must stay:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
TRUST_PROMOTION_ENABLED=false
```

The one-shot preflight uses its own explicit `--allow-network` consent flag. It never overrides or persists those runtime switches.

## What the preflight validates

For the oldest pending item in the selected registered monitor, the script:

1. measures Supabase, Backblaze B2, and Qdrant capacity against the operator-approved internal ceilings;
2. re-validates the queued URL against the source HTTPS allow-list immediately before download;
3. downloads the public source through the normal trusted downloader;
4. extracts text with the normal HTML/PDF/text/XML extractor;
5. rejects anti-bot/challenge pages with the existing quality gate;
6. chunks the document using normal production chunk settings;
7. applies source-specific publication-date extraction;
8. runs structured-claim extraction and eligibility filtering in memory;
9. checks whether the content hash is already represented by an existing document; and
10. verifies that queue state, knowledge-table counts, B2 storage usage, and Qdrant point count did not change.

## What it does not do

The preflight does not:

- change the discovery row;
- increment queue attempt counters;
- create a monitor audit row;
- create or update a document;
- create claims, supersessions, verification events, or trust events;
- upload raw evidence to Backblaze B2;
- create Qdrant vectors;
- mark an item ingested or duplicate;
- enable any scheduler or automatic worker; or
- perform any financial action.

## One-shot command

Run only from the configured private Codespace/environment that already contains the project's existing `.env` values:

```bash
MONITOR_SUPABASE_MAX_MB=400 \
MONITOR_B2_MAX_MB=8192 \
MONITOR_QDRANT_MAX_POINTS=100000 \
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10 \
python scripts/phase7_preflight_pending_discovery.py --allow-network
```

The limits above are the previously validated conservative project safety ceilings, not provider-enforced quotas.

## Why preflight comes before controlled ingestion

The existing ingestion pipeline writes to three independent systems: private object storage, Qdrant, and PostgreSQL. Those systems do not share one atomic transaction. Phase 7 therefore observes the real queued source shape first and verifies that normal extraction succeeds before designing a controlled single-item write with explicit cross-store reconciliation and failure handling.

Automatic queue ingestion remains disabled until that write boundary is tested against real evidence.
