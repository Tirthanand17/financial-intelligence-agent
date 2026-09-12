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

The one-shot tools use explicit command-line consent flags. They never override or persist those runtime switches.

## Read-only preflight

For the oldest pending item in the selected registered monitor, the preflight:

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

The preflight does not change the discovery row, create knowledge rows, upload raw evidence, create vectors, or promote trust.

### Real validation completed

On 2026-09-12 the configured Codespace successfully preflighted the persisted RBI queue item:

```text
RBI announces OMO Sale of Government of India Securities
publication_date=2026-09-11
content_type=text/html
bytes=113676
text_chars=8300
chunks=3
eligible_claims=8
sha256=fe64bd310a664f0a694bc25aaf770c62d15ce3392171d35287899b1b92f81630
existing_document=no
Backblaze delta=0
Qdrant delta=0
```

The run ended `PASS-READ-ONLY`, proving that the real queued source can pass the normal trusted extraction path without mutating queue or knowledge state.

## One-shot read-only command

```bash
MONITOR_SUPABASE_MAX_MB=400 \
MONITOR_B2_MAX_MB=8192 \
MONITOR_QDRANT_MAX_POINTS=100000 \
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10 \
python scripts/phase7_preflight_pending_discovery.py --allow-network
```

The limits above are the previously validated conservative project safety ceilings, not provider-enforced quotas.

## Controlled single-item write boundary

The next checkpoint persists **at most one** pending discovery and is still not a scheduler or autonomous worker.

The first live write attempt exposed an important property of the RBI HTML page: its raw HTML bytes can vary between requests even when the accepted article content is effectively the same. The read-only preflight was 113676 bytes, while a later preflight was 113679 bytes. A second download inside ingestion therefore failed the exact-hash guard before any knowledge/storage/vector write. The queue recorded a symbolic validation failure, and measured deltas remained zero for documents, claims, B2 and Qdrant.

That failure was safe but showed that a two-download design creates an unnecessary time-of-check/time-of-use problem for dynamic HTML. Phase 7 now uses a stronger boundary:

1. perform exactly one trusted public-source download;
2. validate those bytes fully in memory through URL policy, extraction, challenge-page rejection, chunking, publication-date parsing, and claim eligibility;
3. retain the accepted `DownloadedDocument` only in memory and exclude its raw bytes from normal object representation;
4. pass those **exact same validated bytes** into the normal persistence pipeline; and
5. revalidate source/final URLs plus the expected SHA-256 before any persistence begins.

This means controlled ingestion no longer needs a second RBI request. It does not weaken the hash requirement; instead it guarantees that the bytes persisted are exactly the bytes that passed preflight.

The controlled write calls the existing bounded queue processor for exactly one item and then reconciles:

- discovery row identity, status, attempt counter, symbolic error code, and document linkage;
- document, claim, attribution, supersession, verification, and trust-event counts;
- Backblaze B2 byte delta;
- Qdrant point delta; and
- post-write cloud capacity.

A successful new document must produce exactly one new document row, B2 growth equal to the preflighted raw byte count, and Qdrant growth equal to the preflighted chunk count. A duplicate must create no new document, object, or vector points. Trust-event count must remain unchanged in both cases.

Because PostgreSQL, B2, and Qdrant do not share one atomic transaction, a detected post-write mismatch is reported as `RECONCILIATION-REQUIRED`. Existing data is preserved rather than silently deleted.

## Controlled one-item command

Run only after the read-only preflight has passed and only from the configured private Codespace:

```bash
MONITOR_SUPABASE_MAX_MB=400 \
MONITOR_B2_MAX_MB=8192 \
MONITOR_QDRANT_MAX_POINTS=100000 \
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10 \
python scripts/phase7_controlled_ingest_one.py --allow-network --allow-write
```

`--allow-write` is an explicit one-run consent flag. The normal monitoring, automatic-ingestion, and trust-promotion settings remain false before and after the command.

## Why this remains controlled

The existing ingestion pipeline writes to three independent systems: private object storage, Qdrant, and PostgreSQL. Those systems do not share one atomic transaction. Phase 7 therefore advances in bounded checkpoints: observe the real queued source shape, preserve the exact preflighted bytes in memory, process exactly one queue item, and reconcile every affected store before any recurring worker is considered.

Automatic queue ingestion remains disabled until this real one-item write boundary has also been validated.
