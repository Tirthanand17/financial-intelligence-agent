# Phase 15 — Multi-Source Expansion Readiness

Phase 14 proved one cadence-eligible source-monitor cycle can be followed by exactly one bounded evidence ingestion while trust promotion remains disabled.

Phase 15 expands source coverage conservatively, one source at a time. The initial read-only inventory confirmed eight enabled trusted sources, one approved monitor (RBI), and three unmonitored India Authority-A sources: SEBI, NSE, and MoSPI.

## SEBI checkpoint

The official SEBI RSS endpoint `https://www.sebi.gov.in/sebirss.xml` was independently probed read-only. The live probe fetched only the RSS XML once, followed no discovered item URLs, discovered 10 allow-listed SEBI items, rejected 0, and made no PostgreSQL, Backblaze B2, or Qdrant writes. The observed feed items did not provide publication dates, so `publication_date=None` remains an explicit supported state rather than being inferred from retrieval time.

After that successful probe, Phase 15 registers exactly one new monitor:

- monitor ID: `sebi-rss`
- source: `sebi`
- URL: `https://www.sebi.gov.in/sebirss.xml`
- interval: 60 minutes
- maximum discoveries per run: 10

Registration alone does not authorize live monitoring, automatic ingestion, trust promotion, recurring scheduling, or item-detail fetching. `SOURCE_MONITORING_ENABLED`, `SOURCE_AUTO_INGEST_ENABLED`, and `TRUST_PROMOTION_ENABLED` remain false by default.

The next controlled checkpoint after registration readiness is discovery-metadata persistence for SEBI only. That checkpoint may commit bounded monitor run/state/discovery queue metadata to PostgreSQL, but must create no documents, claims, trust events, Backblaze B2 objects, or Qdrant points. It must then prove idempotent re-observation before any one-item exact-byte ingestion canary is considered.

NSE and MoSPI remain unregistered until SEBI independently passes these staged checks.
