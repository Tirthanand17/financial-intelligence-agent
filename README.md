# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 4 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small while preserving evidence, provenance, version history, claim state, entity attribution, source independence, and trust-promotion auditability.

It can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text and supported RSS/Atom/XML feeds with redirect and size checks;
3. reject obvious anti-bot/challenge pages and document URLs that collapse to an unrelated source homepage;
4. retry bounded transient network failures without retrying policy/safety failures;
5. preserve the original file in S3-compatible private object storage;
6. record document provenance in hosted PostgreSQL;
7. extract and chunk text;
8. generate embeddings with Qdrant Cloud Inference (no local embedding-model download);
9. index searchable knowledge in Qdrant Cloud;
10. extract explicit structured numeric claims without inventing values;
11. attach publication/effective dates only when explicitly supported by local or source-specific evidence;
12. resolve known canonical subjects from explicit local aliases such as `RBI`, `SEBI`, `NSE`, `MoSPI`, `World Bank`, or `IMF`;
13. refuse to guess a non-default subject when multiple known entities occur in the local evidence window;
14. normalize only a leading alias for the already-resolved entity, for example `RBI Policy Repo Rate` -> `Policy Repo Rate`;
15. persist entity-attribution provenance separately from the claim itself;
16. preserve source-local version history instead of deleting older claims;
17. reconcile independent-source agreement/disagreement with append-only verification audit events;
18. group sibling brands from the same publisher so they do not count as independent corroboration;
19. evaluate conservative VERIFIED -> TRUSTED promotion rules with append-only trust audit events;
20. keep live automatic trust promotion disabled by default behind `TRUST_PROMOTION_ENABLED=false` until real dated primary + independent evidence passes end-to-end validation;
21. expose entity-attribution provenance in structured QA evidence; and
22. answer suitable factual questions from structured claim state first, while refusing to present conflicted or superseded values as current facts.

The trusted source registry currently includes RBI, SEBI, NSE, MoSPI, World Bank, IMF, DD News, and Akashvani News. DD News and Akashvani are assigned the same `prasar_bharati` independence group so they cannot falsely satisfy an independent-corroboration requirement by themselves. Automated continuous crawling is intentionally not enabled yet.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume your PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — provenance, structured claims, entity attribution, verification events, supersession history, and trust events
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
- `claim_supersessions` — non-destructive source-local version history;
- `claim_verification_events` — append-only verification/conflict transitions; and
- `claim_trust_events` — append-only VERIFIED -> TRUSTED transitions and corroborating source IDs.

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
        ↓
(optional, gated) authority-A direct primary + qualified independent corroboration
        ↓
trusted
```

A disagreement in the same comparable temporal scope becomes `conflicted`. A later dated version from the same source may mark an older version `superseded`, while preserving the older row and an audit link.

`TRUSTED` is deliberately stronger than ordinary verification. The policy requires a VERIFIED, dated, direct authority-A primary claim, auditable entity attribution, no active independent conflict, and at least one independent authority-A/B corroborating publisher group with the same value and temporal scope.

Live automatic trust promotion remains disabled by default:

```text
TRUST_PROMOTION_ENABLED=false
```

The code path is fully tested in isolation, but the switch must remain off until real dated primary + independent evidence has passed live validation.

## Source independence

Different websites or brands owned by the same publisher are not automatically independent.

For example, DD News and Akashvani News are both grouped under `prasar_bharati`. Two agreeing claims from those sibling brands can still be useful evidence, but they count as one publisher-level group for verification/trust policy.

## Entity attribution safety

A source document and the subject of a claim are not assumed to be the same thing.

For example, an IMF or news document can explicitly discuss an RBI policy rate. The system can assign that claim to `Reserve Bank of India` only when the local evidence explicitly identifies that subject. Unsafe source-default cross-entity claims can be withheld from structured persistence while the raw evidence remains preserved.

The attribution decision is auditable. Extracted claims can carry:

- attribution basis (`explicit_local_alias`, `source_default`, or `ambiguous_local_entities_defaulted`);
- source/default entity;
- matched aliases;
- ambiguity candidates; and
- the exact normalized local text window used for the decision.

That metadata is persisted in `claim_entity_attributions` and is also surfaced in structured QA evidence.

## Temporal safety

The system does not use retrieval time as an effective or publication date.

Publication/effective dates are attached only when explicit local text or a conservative source-specific adapter supports them. If a reliable date is absent, the claim remains undated and cannot automatically participate in temporal cross-source verification/trust.

This is why the original stored RBI homepage rate claims remain `candidate`: the page exposes the current rate table but does not provide a reliable explicit effective/publication date tied to those policy-rate values.

Phase 4 added source-specific publication-date adapters for RBI press-release style pages, DD News article timestamps, and Akashvani News article timestamps. RSS/Atom/XML feed extraction preserves each feed item's own publication date and text without automatically following embedded links.

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
- `superseded` or `rejected` values are not presented as current structured facts;
- structured evidence includes entity-attribution provenance when available; and
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

## Validation utilities

The repository includes safe validation/reporting scripts:

```bash
python scripts/rbi_smoke_test.py
python scripts/validate_ddnews_repo_rate.py
python scripts/validate_rbi_june_repo_rate.py
python scripts/trust_readiness_report.py
```

The trust-readiness report is read-only: it evaluates current persisted claims under the Phase 4 policy without changing claim states or creating trust audit rows.

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

Phase 3 added conservative canonical entity attribution and persisted attribution provenance.

Phase 4 now includes:

- conservative trust policy and persistent trust audit events;
- publisher-level independence groups;
- safe structured-claim eligibility filtering;
- DD News and Akashvani secondary-source support;
- source-specific dated metadata adapters;
- bounded transient-download retries;
- RSS/Atom/XML extraction without following embedded links;
- a disabled-by-default ingestion trust-promotion gate;
- peer-group trust reconciliation so a primary can be revisited when corroboration arrives later;
- a read-only trust-readiness report; and
- attribution-aware structured QA evidence.

Latest Phase 4 automated validation: `151 passed, 2 warnings`. The warnings are existing Starlette/anyio deprecations and are non-blocking.

The real DD News June 5, 2026 corroborating article was accepted into the live cloud pipeline. Direct retrieval of the dated RBI June 2026 primary page was blocked by RBI's anti-bot challenge, and the system correctly rejected that response instead of bypassing the protection or promoting trust.

## Current boundary

The trust mechanism is implemented and tested, but live `TRUSTED` promotion is intentionally not enabled because the dated primary RBI evidence has not yet been safely accepted into the live pipeline. The project must not weaken anti-bot protections, invent dates, or treat secondary corroboration as a substitute for direct primary evidence.

Automated continuous crawling and autonomous financial actions remain outside this milestone.

## Next milestone

`scheduled source monitoring -> pause-on-capacity safeguards -> ingestion observability -> conservative review/approval workflow for enabling live trust promotion after dated primary evidence is accepted`
