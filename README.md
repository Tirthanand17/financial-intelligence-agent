# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 1 milestone

The project uses a cloud-first, source-grounded pipeline designed to keep local PC storage very small.

It can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text with redirect and size checks;
3. preserve the original file in S3-compatible private object storage;
4. record provenance in hosted PostgreSQL;
5. extract and chunk text;
6. generate embeddings with Qdrant Cloud Inference (no local embedding-model download);
7. index searchable knowledge in Qdrant Cloud; and
8. answer questions from retrieved evidence with source URLs and confidence.

The first trusted registry includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Automated continuous crawling is intentionally not enabled yet.

## Cloud-first architecture

- **GitHub Private** — source code and version control
- **GitHub Codespaces** — development compute so the project does not consume your PC disk
- **FastAPI** — API layer
- **Supabase PostgreSQL** — structured provenance and later facts/events
- **Qdrant Cloud** — vector retrieval plus server-side embeddings
- **Cloudflare R2** — raw documents/evidence through its S3-compatible API
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

### 3. Cloudflare R2

Create an R2 bucket named `financial-intelligence`, create an S3-compatible API token, and set:

- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET`

Never commit these secrets.

## Recommended development workflow: GitHub Codespaces

1. Open this repository on GitHub.
2. Select **Code -> Codespaces -> Create codespace**.
3. Ensure the codespace is on branch `phase-1-foundation`.
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

By default this ingests an official RBI source and asks a broad question about the retrieved economic content.

You can also supply a specific official RBI HTML/PDF URL and your own question:

```bash
python scripts/rbi_smoke_test.py "https://<official-rbi-url>" "What does this document say about inflation?"
```

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
  "url": "https://bulletin.rbi.org.in/"
}
```

Only HTTPS URLs whose host is explicitly allow-listed for the selected source are accepted.

### Ask a question

```http
POST /ask
Content-Type: application/json

{
  "question": "What economic developments are discussed?",
  "source_id": "rbi",
  "top_k": 5
}
```

Current answers use **extractive grounded mode**. The system selects statements from retrieved source evidence rather than asking a generative model to invent an answer. Each response includes evidence, source URL, retrieval score, source authority level, and retrieval timestamp.

## Data safety

Do not commit API keys, passwords, downloaded PDFs, databases, embeddings, or large financial datasets. `.gitignore` excludes local secrets and data. Raw documents remain in private object storage.

For Codespaces, store credentials as Codespaces secrets when possible instead of keeping long-lived credentials in files.

## Important design rule

New internet material is not automatically treated as truth. Source identity and provenance are preserved first. Later phases will add claim extraction, cross-source verification, contradiction handling, temporal versioning, and knowledge promotion states such as `candidate`, `verified`, `trusted`, `superseded`, and `rejected`.

## Next milestone

After Phase 1 cloud validation:

`RBI ingestion -> structured claim extraction -> publication/effective dates -> verification -> PostgreSQL facts -> improved grounded answers`

Only after that will scheduled continuous learning be enabled.
