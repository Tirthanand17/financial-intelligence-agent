# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 5 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small while preserving evidence, provenance, version history, claim state, entity attribution, source independence, trust-promotion auditability, and monitoring history.

It can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text and supported RSS/Atom/XML feeds with redirect and size checks;
3. reject obvious anti-bot/challenge pages and document URLs that collapse to an unrelated source homepage;
4. retry bounded transient network failures without retrying policy/safety failures;
5. preserve original evidence in S3-compatible private object storage;
6. record document provenance in hosted PostgreSQL;
7. extract and chunk text;
8. generate embeddings with Qdrant Cloud Inference without a local embedding-model download;
9. index searchable knowledge in Qdrant Cloud;
10. extract explicit structured numeric claims without inventing values;
11. attach publication/effective dates only when explicit evidence supports them;
12. resolve known canonical entities conservatively and persist attribution provenance;
13. preserve source-local claim version history instead of deleting older claims;
14. reconcile independent-source agreement/disagreement with append-only verification audit events;
15. group sibling brands from the same publisher so they do not falsely count as independent corroboration;
16. evaluate conservative VERIFIED -> TRUSTED promotion rules with append-only trust audit events;
17. keep live automatic trust promotion disabled by default behind `TRUST_PROMOTION_ENABLED=false`;
18. answer suitable factual questions from structured claim state first while refusing to present conflicted or superseded values as current facts;
19. monitor only explicitly configured, allow-listed feeds behind `SOURCE_MONITORING_ENABLED=false` by default;
20. discover a bounded number of allow-listed RSS/Atom item URLs without following them;
21. persist discoveries idempotently as pending work with non-secret operational metadata;
22. pause automatic work when required cloud-capacity information is missing, low, or exhausted instead of deleting evidence or reducing source quality;
23. require a separate `SOURCE_AUTO_INGEST_ENABLED=false` gate before queued URLs can reach the trusted ingestion pipeline;
24. revalidate every queued URL immediately before ingestion; and
25. provide read-only trust-readiness and monitoring-status reports.

The trusted source registry currently includes RBI, SEBI, NSE, MoSPI, World Bank, IMF, DD News, and Akashvani News. DD News and Akashvani are assigned the same `prasar_bharati` independence group so they cannot falsely satisfy an independent-corroboration requirement by themselves.

Phase 5 does **not** enable unrestricted crawling, a scheduled live cloud monitor, automatic trust promotion, or autonomous financial actions.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume the local PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — provenance, structured claims, attribution, verification/trust audits, and monitoring metadata
- **Qdrant Cloud** — vector retrieval plus server-side embeddings
- **Backblaze B2** — private raw documents/evidence through its S3-compatible API
- **GitHub Actions** — automatic cloud tests on `main`, `phase-*` branches, and pull requests to `main`

Docker is not required for the recommended setup.

## Local PC storage policy

The recommended workflow does not install PostgreSQL, Qdrant, MinIO, Docker images, or embedding models on the PC.

Do not store downloaded research documents, databases, embeddings, model weights, or large temporary files in the repository. See `docs/DATA_AND_STORAGE_POLICY.md` for the authoritative policy. Knowledge quality, provenance, history, evaluations, or source coverage must never be silently reduced to save disk space.

## Cloud services

### Supabase PostgreSQL

Use a hosted PostgreSQL connection string in `DATABASE_URL`.

Important tables include:

- `documents` — source provenance and raw-object references;
- `claims` — structured claim facts and current state;
- `claim_entity_attributions` — auditable canonical-subject attribution;
- `claim_supersessions` — non-destructive source-local version history;
- `claim_verification_events` — append-only verification/conflict transitions;
- `claim_trust_events` — append-only VERIFIED -> TRUSTED transitions;
- `source_monitor_states` — current non-secret monitor state;
- `source_monitor_runs` — append-only monitor run history; and
- `source_monitor_discoveries` — idempotent pending/processed feed discoveries.

### Qdrant Cloud

Configure `QDRANT_URL` and `QDRANT_API_KEY`. The default embedding model is:

`sentence-transformers/all-MiniLM-L6-v2`

Embeddings are created in Qdrant Cloud instead of being downloaded to the developer machine.

### Backblaze B2

Use a private bucket with a bucket-scoped S3-compatible application key and configure:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`
- `S3_REGION`

Never commit these secrets.

## Recommended development workflow: GitHub Codespaces

1. Open this repository on GitHub.
2. Select **Code -> Codespaces -> Create codespace**.
3. Use the current `phase-*` branch while a milestone is under review.
4. The dev-container setup installs Python dependencies automatically in the cloud.
5. Keep private cloud credentials in the Codespace environment or `.env`; never commit them.

For local/manual validation when genuinely needed:

```bash
pytest -q
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Routine tests run automatically in GitHub Actions after pushed changes.

## Trusted ingestion and claim lifecycle

New internet material is never automatically treated as truth.

```text
allow-listed source document
        ↓
raw evidence + document provenance
        ↓
explicit structured fact
        ↓
local entity/date attribution with provenance
        ↓
candidate
        ↓
independent, comparable corroboration
        ↓
verified
        ↓
(optional, gated) authority-A direct primary + qualified independent corroboration
        ↓
trusted
```

A disagreement in the same comparable temporal scope becomes `conflicted`. A later dated version from the same source may mark an older version `superseded`, while preserving the older row and audit history.

`TRUSTED` is deliberately stronger than ordinary verification. Live automatic promotion remains disabled by default:

```text
TRUST_PROMOTION_ENABLED=false
```

The switch must remain off until real dated primary + independent evidence has passed live validation.

## Source independence

Different websites or brands owned by the same publisher are not automatically independent. DD News and Akashvani News, for example, share the `prasar_bharati` publisher-level independence group.

## Entity attribution safety

A source document and the subject of a claim are not assumed to be the same thing. An IMF or news document can explicitly discuss an RBI policy rate; the system assigns the canonical subject only when local evidence supports that attribution. Unsafe cross-entity claims can be withheld from structured persistence while preserving the raw evidence.

Attribution metadata includes basis, source/default entity, matched aliases, ambiguity candidates, and the normalized local evidence window used for the decision.

## Temporal safety

Retrieval time is never used as an invented effective/publication date. Dates are attached only when explicit local text or a conservative source-specific adapter supports them. Undated claims cannot automatically participate in temporal cross-source verification/trust.

This is why the original stored RBI homepage rate claims remain `candidate`: the page exposes the current rate table but does not reliably tie those values to an explicit effective/publication date.

## Phase 5 source monitoring

Phase 5 adds bounded monitoring without turning the project into an unrestricted crawler. The detailed design is in `docs/PHASE5_SOURCE_MONITORING.md`.

The two runtime gates are independent and both default to false:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
```

The first gate allows only a registered monitor feed to be observed. The second is additionally required before a pending discovery may be passed to the existing trusted ingestion pipeline. Enabling monitoring therefore does not silently enable item-link ingestion.

The current RBI monitor is explicitly configured for the RBI press-release RSS feed, with a minimum one-hour cadence and bounded per-run discovery count. Failure scheduling uses exponential backoff capped at 24 hours.

### Capacity safeguards

Automatic monitoring/processing requires capacity signals for Supabase, Backblaze B2, and Qdrant. Provider quotas are never guessed. If usage or an operator-approved ceiling is missing, capacity is `UNKNOWN` and automatic work pauses.

Optional ceilings remain unset by default:

```text
MONITOR_SUPABASE_MAX_MB=
MONITOR_B2_MAX_MB=
MONITOR_QDRANT_MAX_POINTS=
MONITOR_CAPACITY_LOW_WATERMARK_PERCENT=10
```

Low/exhausted capacity pauses work. It does not silently delete evidence, truncate history, or reduce source quality.

### Discovery queue and processing

Feed discovery validates HTTPS and the trusted-source host allow-list, deduplicates feed URLs, and stores bounded discoveries in `source_monitor_discoveries`. Discovery itself does not download item links.

If auto-ingestion is explicitly enabled later, the processor:

1. requires monitoring + auto-ingestion gates;
2. requires the monitor to be enabled and cloud capacity safe;
3. selects only a bounded pending batch for that monitor/source;
4. revalidates every queued URL immediately before ingestion;
5. passes eligible URLs through the existing trusted ingestion pipeline; and
6. stores only symbolic operational errors rather than raw exception text or secrets.

A policy-invalid queued URL becomes `rejected`; transient/operational failures stay `pending` for later retry. Successfully indexed items become `ingested`; already-known documents become `duplicate`.

No scheduled live cloud job has been enabled in this milestone.

## Grounded question answering

### Ask a question

```http
POST /ask
Content-Type: application/json

{
  "question": "What is the policy repo rate?",
  "source_id": "rbi",
  "top_k": 5
}
```

For suitable metric questions, the structured layer is checked before vector retrieval:

- `trusted` / `verified` structured claims are preferred when available;
- latest comparable temporal scope is preferred over older dated history;
- `candidate` values may be returned with lower confidence and an explicit candidate basis;
- `conflicted` claims are surfaced as a conflict instead of selecting one value;
- `superseded` or `rejected` values are not presented as current structured facts; and
- questions that do not map safely to structured claims fall back to extractive evidence retrieval from Qdrant.

Every response remains grounded in stored evidence and includes a non-advice warning.

## API endpoints

### Health

```text
GET /health
```

### List trusted sources

```text
GET /sources
```

### Ingest a trusted document

```http
POST /ingest
Content-Type: application/json

{
  "source_id": "rbi",
  "url": "https://www.rbi.org.in/"
}
```

Only HTTPS URLs whose host is explicitly allow-listed for the selected source are accepted.

### Ask

```text
POST /ask
```

## Validation and reporting utilities

```bash
python scripts/rbi_smoke_test.py
python scripts/validate_ddnews_repo_rate.py
python scripts/validate_rbi_june_repo_rate.py
python scripts/trust_readiness_report.py
python scripts/monitoring_status_report.py
```

`trust_readiness_report.py` is read-only and evaluates persisted claim readiness without changing claim states or audit rows. `monitoring_status_report.py` is also read-only and reports the two Phase 5 gates plus aggregate persisted monitor/run/discovery state without network access or mutations.

If an official site returns a CAPTCHA/challenge page or silently redirects a document URL to an unrelated homepage, ingestion rejects that response instead of treating it as trusted evidence.

## Cleanup of rejected evidence

The repository includes a cleanup utility for previously indexed RBI challenge pages or invalid redirected records:

```bash
python scripts/purge_challenge_pages.py
python scripts/purge_challenge_pages.py --apply
```

Run without `--apply` first to preview what would be removed.

## Validation status

Phase 1 established real-cloud consistency across Supabase PostgreSQL, Backblaze B2, and Qdrant Cloud.

Phase 2 added structured claims, temporal metadata, supersession, verification/conflict state transitions, append-only audit history, ingestion reconciliation, and claim-aware QA. The real RBI homepage backfill is idempotent and contains 11 candidate structured rate claims.

Phase 3 added conservative canonical entity attribution and persisted attribution provenance.

Phase 4 added conservative trust policy, publisher-level independence, source-specific dated metadata, DD News/Akashvani support, bounded transient retries, RSS/Atom extraction, peer-group trust reconciliation, a read-only trust-readiness report, and attribution-aware structured QA evidence. The real DD News June 5, 2026 corroborating article was accepted. Direct retrieval of the dated RBI June 2026 primary page was blocked by RBI anti-bot protection and correctly rejected without bypassing it or promoting trust.

Phase 5 currently adds:

- bounded source-specific monitoring definitions;
- minimum cadence and failure backoff;
- fail-closed Supabase/B2/Qdrant capacity policy with no guessed quotas;
- append-only monitor run observability plus current monitor state;
- bounded allow-listed RSS/Atom discovery;
- an idempotent persistent discovery queue;
- a global monitoring gate and separate automatic-ingestion gate, both disabled by default;
- immediate URL revalidation before queued ingestion;
- bounded processing through the existing trusted ingestion pipeline;
- symbolic secret-free failure recording; and
- a read-only monitoring status report.

Latest Phase 5 automated validation: `204 passed, 2 warnings`. The two warnings are the existing Starlette/httpx and AnyIO deprecations and are non-blocking.

## Current boundary

The Phase 5 monitoring and queued-processing architecture is implemented and tested, but live scheduled monitoring has **not** been enabled. `SOURCE_MONITORING_ENABLED=false`, `SOURCE_AUTO_INGEST_ENABLED=false`, and `TRUST_PROMOTION_ENABLED=false` remain the safe defaults.

Before live scheduling, the project still needs measured cloud-usage inputs, deliberately chosen safe ceilings, and a controlled source-monitor probe. It must not guess quotas, weaken source/anti-bot protections, invent dates, delete trusted history to make space, or perform autonomous financial actions.

## Next milestone

`measured cloud-capacity collectors -> controlled read-only/live monitor probe -> scheduler deployment only after explicit safe ceilings are configured -> continued conservative evidence review`
