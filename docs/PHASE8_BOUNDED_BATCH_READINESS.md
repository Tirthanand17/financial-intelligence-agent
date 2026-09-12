# Phase 8 — Bounded Batch Readiness

Phase 8 validates that a small set of queued RBI discoveries can pass the trusted preflight path together before any recurring or autonomous processing is enabled.

## Safety boundary

The Phase 8 canary is read-only. It requires all three live gates to remain disabled:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`

It also requires cloud capacity to be explicitly within the approved operator ceilings before any public-source download is attempted.

## Canary bounds

The batch preflight is deliberately small:

- maximum selected items: 3
- maximum aggregate downloaded content: 5 MiB
- every item must pass the existing trusted downloader, URL allow-list, anti-bot/challenge rejection, extraction, chunking, publication-date parsing, and claim-eligibility path
- a valid document may contain zero currently extractable scalar claims
- every selected item must have an explicit publication date

The script defensively rolls back the SQLAlchemy session and compares before/after snapshots of the selected queue rows, monitoring tables, Backblaze B2 usage, and Qdrant point count. Any change blocks readiness.

## Validated live result

On 2026-09-12, a real read-only canary selected three pending RBI press-release discoveries:

1. `RBI to conduct Overnight Variable Rate Reverse Repo (VRRR) auction under LAF on September 15, 2026`
   - publication date: 2026-09-11
   - bytes: 111,475
   - chunks: 3
   - eligible claims: 1
2. `Money Supply for the fortnight ended on August 31, 2026`
   - publication date: 2026-09-11
   - bytes: 110,360
   - chunks: 2
   - eligible claims: 0
3. `Government Stock - Full Auction Results`
   - publication date: 2026-09-11
   - bytes: 115,179
   - chunks: 3
   - eligible claims: 6

Aggregate bytes were 337,014. All three items passed. Backblaze B2 and Qdrant deltas were both zero, and no queue/database state changed.

## Completion criterion

Phase 8 is complete when:

- CI is green,
- the real three-item canary passes,
- no queue/database/object/vector mutation occurs,
- and all three live automation/trust gates remain disabled.

Passing Phase 8 does **not** authorize scheduled monitoring, automatic ingestion, trust promotion, or trading actions. It only establishes that the next controlled ingestion batch can be tested under an explicit write bound.
