# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 1 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small.

It can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text with redirect and size checks;
3. reject obvious anti-bot/challenge pages and document URLs that collapse to an unrelated source homepage;
4. preserve the original file in S3-compatible private object storage;
5. record provenance in hosted PostgreSQL;
6. extract and chunk text;
7. generate embeddings with Qdrant Cloud Inference (no local embedding-model download);
8. index searchable knowledge in Qdrant Cloud; and
9. answer questions from retrieved evidence with source URLs, confidence, and confidence basis.

The first trusted registry includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Automated continuous crawling is intentionally not enabled yet.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume your PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — structured provenance and later facts/events
- **Qdrant Cloud** — vector retrieval plus server-side embeddings
- **Backblaze B2** — private raw documents/evidence through its S3-compatible API
- **GitHub Actions** — unit tests in the cloud

Docker is not required for the recommended setup.

## Local PC storage policy

The recommended workflow does not install PostgreSQL, Qdrant, MinIO, Docker images, or embedding models on your PC.

You may keep the Git clone locally because it is very small, or delete it after opening the project in Codespaces. Do not store downloaded research documents or databases in the repository.

## Cloud services to create

### 1. Supabase

Create a free project and obtain a PostgreSQL connection string. Put it in `DATABASE_URL`.

### 2. Qdrant Cloud

Create a free cluster, enable Cloud Inference, and obtain:

- cluster URL -> `QDRANT_URL`
- API key -> `QDRANT_API_KEY`

The default embedding model is:

`sentence-transformers/all-MiniLM-L6-v2`

Embeddings are created in Qdrant Cloud instead of being downloaded to the developer machine.

### 3. Backblaze B2

Create a private B2 bucket, create a bucket-scoped S3-compatible application key, and set:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`
- `S3_REGION`

Use the S3 endpoint and region shown by Backblaze for the bucket. Never commit these secrets.

## Recommended development workflow: GitHub Codespaces

1. Open this repository on GitHub.
2. Select **Code -> Codespaces -> Create codespace**.
3. Ensure the codespace is on branch `phase-1-foundation` while Phase 1 is under review.
4. The dev-container setup installs Python dependencies automatically in the cloud.
5. Create a private `.env` inside the codespace from `.env.example` and fill in the cloud credentials.

Then run:

```bash
pytest -q
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Codespaces will offer to forward port 8000.

## First RBI end-to-end test

With the API running in Codespaces, open a second terminal and execute:

```bash
python scripts/rbi_smoke_test.py
```

By default this ingests the official RBI website and asks for the policy repo rate shown in the retrieved evidence.

You can also supply a specific official RBI HTML/PDF URL and your own question:

```bash
python scripts/rbi_smoke_test.py "https://<official-rbi-url>" "What does this document say about inflation?"
```

If an official site returns a CAPTCHA/challenge page or silently redirects a document URL to an unrelated homepage, ingestion rejects that response instead of treating it as trusted evidence.

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

### Ask a question

```http
POST /ask
Content-Type: application/json

{
  "question": "What policy repo rate is shown on the RBI website?",
  "source_id": "rbi",
  "top_k": 5
}
```

Current answers use **extractive grounded mode**. The system selects statements or structured financial facts from retrieved source evidence rather than asking a generative model to invent an answer. Each response includes evidence, source URL, retrieval score, source authority level, retrieval timestamp, confidence, and `confidence_basis`.

## Cleanup of rejected evidence

For Phase 1 development, the repository includes a cleanup utility for previously indexed RBI challenge pages or invalid redirected records:

```bash
python scripts/purge_challenge_pages.py
python scripts/purge_challenge_pages.py --apply
```

Run without `--apply` first to preview what would be removed.

## Data safety

Do not commit API keys, passwords, downloaded PDFs, databases, embeddings, or large financial datasets. `.gitignore` excludes local secrets and data. Raw documents remain in private object storage.

For Codespaces, store credentials as Codespaces secrets when possible instead of keeping long-lived credentials in files.

## Important design rule

New internet material is not automatically treated as truth. Source identity and provenance are preserved first. Later phases will add claim extraction, cross-source verification, contradiction handling, temporal versioning, and knowledge promotion states such as `candidate`, `verified`, `trusted`, `superseded`, and `rejected`.

## Phase 1 validation

The Phase 1 branch has been validated end-to-end with:

- passing unit tests;
- successful RBI ingestion and grounded QA;
- anti-bot/challenge-page rejection;
- exact structured fact extraction for the RBI policy repo rate;
- confidence calibration with an explicit confidence basis; and
- persistence consistency across Supabase PostgreSQL, Backblaze B2, and Qdrant Cloud.

## Next milestone

After Phase 1 merge:

`trusted ingestion -> structured claim extraction -> publication/effective dates -> verification -> PostgreSQL facts -> contradiction/version handling -> improved grounded answers`

Only after that will scheduled continuous learning be enabled.
