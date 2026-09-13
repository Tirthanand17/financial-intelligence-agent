# Phase 15 — Multi-Source Expansion Readiness

Phase 14 proved one cadence-eligible monitor cycle can be followed by exactly one bounded evidence ingestion while trust promotion remains disabled. Phase 15 expanded that design one India Authority-A source at a time without enabling recurring monitoring, automatic ingestion, or trust promotion.

The trusted-source registry contains eight enabled sources. Phase 15 closes the initial India Authority-A monitoring gap by adding bounded monitors for SEBI, NSE, and MoSPI alongside the existing RBI monitor.

## Safety invariants

Throughout Phase 15:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- no recurring scheduler was enabled;
- publication dates came only from trusted source evidence/metadata, never retrieval time;
- each controlled ingestion persisted the exact bytes that passed the immediately preceding preflight;
- no trust-promotion event was created.

## SEBI checkpoint

The official SEBI RSS endpoint `https://www.sebi.gov.in/sebirss.xml` is registered as `sebi-rss`, with a 60-minute cadence and a maximum of 10 discoveries per run. The live feed probe discovered 10 allow-listed items with 0 rejected items.

SEBI detail pages required a fail-closed wrapper-to-primary-PDF resolver. Cross-host and ambiguous attachment targets are rejected. The controlled canary persisted one validated SEBI PDF with SHA-256 `8dfcb8cbf9d310d949f91343bb0fa2fd2a87bcd5b088cc41818ad418d33a0438`, 402250 exact bytes, and 2 Qdrant chunks. No trust event was created.

## NSE checkpoint

The official NSE Daily Buy Back RSS endpoint `https://nsearchives.nseindia.com/content/RSS/Daily_Buyback.xml` is registered as `nse-daily-buyback-rss`, with a 60-minute cadence and a maximum of 10 discoveries per run. The source policy explicitly allow-lists the first-party NSE archives host and rejects cross-host lookalikes.

The controlled NSE canary preserved the RSS publication date through preflight and ingestion. It persisted one PDF with SHA-256 `2709164379b3987a9aaf448c241ea5355cb3f77b757caf9fb14f1963dcaffe76`, 577212 exact bytes, 1 Qdrant chunk, 4 candidate claims, and publication date `2026-09-11`. No trust event was created.

## MoSPI checkpoint

MoSPI uses the official first-party Latest Releases JSON API `https://www.mospi.gov.in/api/latest-release/get-web-latest-release-list`, registered as `mospi-latest-releases-api`. Discovery is bounded to 10 first-party PDF records and rejects cross-host, non-PDF, malformed, or policy-invalid records.

A live read-only probe discovered 10 first-party release PDFs with 0 rejections. Controlled discovery then persisted 10 queue rows, and an immediate replay created 0 duplicate discovery rows.

The controlled MoSPI canary persisted one PDF with SHA-256 `899c81e1298465249734c8d6168c2b5f2549960a15a3ba23d3b13bb1772f63f6`, 331359 exact bytes, 5 Qdrant chunks, 4 candidate claims, and publication date `2026-09-02`. No trust event was created.

## Closeout criteria

Phase 15 is complete when the read-only closeout audit confirms all four India Authority-A sources have registered monitors, SEBI/NSE/MoSPI each have a linked terminal controlled-canary discovery, all three global gates remain false, and the trust-event table remains empty.

Phase 16 must not simply enable trust promotion. Current trust-readiness review found no promotable persisted claims, and several newly extracted claims are low-value page metadata or malformed numeric fragments. The next phase therefore begins with claim-quality and verification-readiness hardening while trust promotion stays disabled.
