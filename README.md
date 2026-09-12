# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 3 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small while preserving evidence, provenance, version history, claim state, and the reason a canonical subject/entity was assigned to a claim.

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
11. resolve known canonical subjects from explicit local aliases such as `RBI`, `SEBI`, `NSE`, `MoSPI`, `World Bank`, or `IMF`;
12. refuse to guess a non-default subject when multiple known entities occur in the local evidence window;
13. normalize only a leading alias for the already-resolved entity, for example `RBI Policy Repo Rate` -> `Policy Repo Rate`;
14. persist entity-attribution provenance separately from the claim itself;
15. preserve source-local version history instead of deleting older claims;
16. reconcile independent-source agreement/disagreement with append-only verification audit events; and
17. answer suitable factual questions from structured claim state first, while refusing to present conflicted or superseded values as current facts.

The trusted source registry currently includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Automated continuous crawling is intentionally not enabled yet.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume your PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — provenance, structured claims, entity attribution, verification events, and supersession history
- **Qdrant Cloud** — vector retrieval plus server-side embeddings
- **Backblaze B2** — private raw documents/evidence through its S3-compatible API
- **GitHub Actions** — automatic cloud tests on `main`, all `phase-*` branches, and pull requests to `main`

Docker is not required for the recommended setup.

## Local PC storage policy

The recommended workflow does not install PostgreSQL, Qdrant, MinIO, Docker images, or embedding models on your PC.

You may keep the Git clone locally because it is very small, or delete it after opening the project in Codespaces. Do not store downloaded research documents or databases in the repository.

See `docs/DATA_AND_STORAGE_POLICY.md` for the authoritative storage policy. Knowledge quality, provenance, history, evaluations, or source coverage must not be silently reduced to save disk space.

## Cloud services

### 1. Supabase

Use a hosted PostgreSQL connection string in `DATABASE_URL`.

The structured layer uses separate tables so new audit capabilities do not require unsafe in-place changes to the existing `claims` table:

- `documents` — source provenance and raw-object references;
- `claims` — structured claim facts and current state;
- `claim_entity_attributions` — why a canonical subject was assigned, including source default, explicit matched aliases, ambiguity candidates, and the exact local evidence window used;
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
3. Use the current `phase-*` branch while a milestone is under review.
4. The dev-container setup installs Python dependencies automatically in the cloud.
5. Keep private cloud credentials in the Codespace environment or `.env`; never commit them.

For local/manual validation when genuinely needed:

```bash
pytest -q
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Normal unit/integration tests run automatically in GitHub Actions after pushed changes, so routine development does not require manually copying test commands between ChatGPT and Terminal 2.

## Trusted ingestion and claim lifecycle

New internet material is never automatically treated as truth.

The current lifecycle is deliberately conservative:

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
```

A disagreement in the same comparable temporal scope becomes `conflicted`. A later dated version from the same source may mark an older version `superseded`, while preserving the older row and an audit link. `trusted` exists as a reserved stronger state, but the system does not automatically promote claims to trusted merely because extraction or two-source verification succeeded.

## Entity attribution safety

A source document and the subject of a claim are not assumed to be the same thing.

For example, an IMF document can explicitly discuss an RBI policy rate. Phase 3 can assign that claim to `Reserve Bank of India` only when the small local evidence window explicitly contains exactly one recognized RBI name/alias. If both `IMF` and `RBI` occur in the attribution window, the resolver keeps the source/default entity rather than guessing which institution owns the metric.

The attribution decision is auditable. Extracted claims carry:

- attribution basis (`explicit_local_alias`, `source_default`, or `ambiguous_local_entities_defaulted`);
- source/default entity;
- matched aliases;
- ambiguity candidates; and
- the exact normalized local text window used for the decision.

That metadata is persisted in `claim_entity_attributions` without changing the deterministic fact identity. Existing older claims can therefore gain missing attribution provenance idempotently when their preserved evidence is reprocessed.

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

## Validation status

Phase 1 real-cloud validation established consistency across Supabase PostgreSQL, Backblaze B2, and Qdrant Cloud.

Phase 2 added structured claims, temporal metadata, supersession, verification/conflict state transitions, append-only audit history, ingestion reconciliation, and claim-aware QA. The real RBI homepage backfill is idempotent and contains 11 candidate structured rate claims.

Phase 3 automated coverage now includes:

- canonical entity aliases for the current trusted-source set;
- exact alias-boundary protection;
- ambiguous-local-entity refusal-to-guess behavior;
- entity-prefixed metric normalization;
- secondary-source explicit subject attribution;
- end-to-end alignment of primary RBI and explicitly attributed secondary RBI claims for verification;
- persisted entity-attribution provenance in a separate table;
- idempotent attribution persistence and backfill for existing claim identities; and
- protection against inventing attribution metadata for older/manual claims that have no extraction evidence.

Latest Phase 3 automated validation at the attribution-persistence milestone: `99 passed, 2 warnings`. The warnings are existing Starlette/anyio deprecations and are non-blocking.

## Current boundary

The code can now align explicitly attributed secondary evidence with a primary-source entity, but a real independent dated corroborating document has not yet been accepted as proof merely because the mechanism works in tests. Real cross-source corroboration must use actual allow-listed documents whose text explicitly supports the same entity, metric, unit, value, and temporal scope.

Automatic `trusted` promotion, broad free-form entity recognition, broad prose fact extraction, scheduled continuous crawling, and autonomous financial actions remain intentionally outside this milestone.

## Next milestone

`real dated cross-source corroboration -> conservative trust-promotion policy -> attribution-aware QA evidence -> scheduled source monitoring with pause-on-capacity safeguards`
