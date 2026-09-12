# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 2 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small while preserving evidence, provenance, version history, and claim state.

It can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text with redirect and size checks;
3. reject obvious anti-bot/challenge pages and document URLs that collapse to an unrelated source homepage;
4. preserve the original file in S3-compatible private object storage;
5. record document provenance in hosted PostgreSQL;
6. extract and chunk text;
7. generate embeddings with Qdrant Cloud Inference (no local embedding-model download);
8. index searchable knowledge in Qdrant Cloud;
9. extract explicit structured numeric claims without inventing values;
10. attach publication/effective dates only when explicitly supported by nearby evidence;
11. persist claim states such as `candidate`, `verified`, `trusted`, `conflicted`, `superseded`, and `rejected`;
12. preserve source-local version history instead of deleting older claims;
13. reconcile independent-source agreement/disagreement with append-only verification audit events; and
14. answer suitable factual questions from structured claim state first, while refusing to present conflicted or superseded values as current facts.

The trusted source registry currently includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Automated continuous crawling is intentionally not enabled yet.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume your PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — provenance, structured claims, verification events, and supersession history
- **Qdrant Cloud** — vector retrieval plus server-side embeddings
- **Backblaze B2** — private raw documents/evidence through its S3-compatible API
- **GitHub Actions** — automatic cloud tests on the Phase 2 branch and pull requests

Docker is not required for the recommended setup.

## Local PC storage policy

The recommended workflow does not install PostgreSQL, Qdrant, MinIO, Docker images, or embedding models on your PC.

You may keep the Git clone locally because it is very small, or delete it after opening the project in Codespaces. Do not store downloaded research documents or databases in the repository.

See `docs/DATA_AND_STORAGE_POLICY.md` for the authoritative storage policy. Knowledge quality, provenance, history, evaluations, or source coverage must not be silently reduced to save disk space.

## Cloud services

### 1. Supabase

Use a hosted PostgreSQL connection string in `DATABASE_URL`.

Phase 2 stores:

- `documents` — source provenance and raw-object references;
- `claims` — structured claim facts and current state;
- `claim_supersessions` — non-destructive source-local version history; and
- `claim_verification_events` — append-only verification/conflict transitions.

### 2. Qdrant Cloud

Configure:

- cluster URL -> `QDRANT_URL`
- API key -> `QDRANT_API_KEY`

The default embedding model is:

`sentence-transformers/all-MiniLM-L6-v2`

Embeddings are created in Qdrant Cloud instead of being downloaded to the developer machine.

### 3. Backblaze B2

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
3. Use branch `phase-2-structured-claims` while Phase 2 is under review.
4. The dev-container setup installs Python dependencies automatically in the cloud.
5. Keep private cloud credentials in the Codespace environment or `.env`; never commit them.

For local/manual validation when needed:

```bash
pytest -q
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Normal unit/integration tests also run automatically in GitHub Actions when Phase 2 changes are pushed.

## Trusted ingestion and claim lifecycle

New internet material is never automatically treated as truth.

The current lifecycle is deliberately conservative:

```text
trusted-source document
        ↓
raw evidence + provenance
        ↓
explicit structured claim
        ↓
candidate
        ↓
independent dated corroboration
        ↓
verified
```

A disagreement in the same comparable temporal scope becomes `conflicted`. A later dated version from the same source may mark an older version `superseded`, while preserving the older row and an audit link. `trusted` exists as a reserved stronger state, but Phase 2 does not automatically promote claims to trusted merely because extraction or two-source verification succeeded.

## Temporal safety

The system does not use retrieval time as an effective date.

Publication/effective dates are attached only when explicit nearby source text supports them, such as `Published on`, `Effective Date`, `With effect from`, or similar labelled forms. If a reliable date is absent, the claim remains undated and cannot automatically participate in temporal cross-source verification.

This is why the currently stored RBI homepage rate claims remain `candidate`: the page exposes the current rate table but does not provide a reliable explicit effective/publication date next to those values.

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

For suitable metric questions, Phase 2 checks persisted structured claims before vector retrieval:

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

## First RBI end-to-end validation

With the API running in Codespaces:

```bash
python scripts/rbi_smoke_test.py
```

If an official site returns a CAPTCHA/challenge page or silently redirects a document URL to an unrelated homepage, ingestion rejects that response instead of treating it as trusted evidence.

## Cleanup of rejected evidence

The repository includes a cleanup utility for previously indexed RBI challenge pages or invalid redirected records:

```bash
python scripts/purge_challenge_pages.py
python scripts/purge_challenge_pages.py --apply
```

Run without `--apply` first to preview what would be removed.

## Phase 2 validation status

Phase 2 has automated coverage for:

- canonical structured claim schema and deterministic fingerprints;
- idempotent PostgreSQL claim persistence;
- one-line and split-line financial fact extraction;
- prevention of period/year false positives;
- explicit temporal metadata parsing and local date attachment;
- source-local supersession/version decisions;
- persisted supersession audit history;
- independent-source verification/conflict decisions;
- persisted verification transition audit history;
- ingestion-time supersession and verification reconciliation;
- claim-aware grounded QA that protects against conflicted/superseded current answers; and
- backward-compatible extractive Qdrant fallback.

Real Phase 1 evidence remains consistent across Supabase, Backblaze B2, and Qdrant. The real RBI homepage claim backfill is idempotent and currently contains 11 candidate structured rate claims.

## Known Phase 2 boundary

Cross-source verification requires claims to share the same canonical entity, metric, unit, and temporal scope. The current conservative extractor assigns the primary source entity supplied by ingestion and does not yet perform broad free-form entity attribution. Therefore real cross-source corroboration should not be considered complete until explicit subject/entity attribution is added and validated against real corroborating documents.

Automated continuous crawling, broad prose fact extraction, automatic `trusted` promotion, and autonomous financial actions are intentionally outside the current milestone.

## Next milestone

After Phase 2 review and merge:

`explicit entity attribution -> real dated cross-source corroboration -> trust-promotion policy -> claim-aware retrieval expansion -> scheduled source monitoring with pause-on-capacity safeguards`
