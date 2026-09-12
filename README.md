# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Current Phase 1 milestone

The project now has a local-first, source-grounded pipeline that can:

1. accept a URL only from an allow-listed trusted source;
2. download HTML/PDF/text with redirect and size checks;
3. preserve the original file in MinIO;
4. record provenance in PostgreSQL;
5. extract and chunk text;
6. create local embeddings with FastEmbed;
7. index searchable knowledge in Qdrant; and
8. answer questions from retrieved evidence with source URLs and confidence.

The first trusted registry includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Automated continuous crawling is intentionally not enabled yet.

## Architecture

- **FastAPI** — API layer
- **PostgreSQL** — document provenance and later structured facts/events
- **Qdrant** — semantic/vector retrieval
- **MinIO** — raw source documents/evidence
- **FastEmbed** — local embeddings; no paid embedding API required
- **Docker Compose** — local infrastructure

## Local setup (Windows)

### 1. Prerequisites

Install Python 3.11+, Git, and Docker Desktop.

### 2. Clone and enter the repository

```powershell
git clone https://github.com/Tirthanand17/financial-intelligence-agent.git
cd financial-intelligence-agent
git checkout phase-1-foundation
```

### 3. Create local environment configuration

```powershell
Copy-Item .env.example .env
```

Change the placeholder PostgreSQL and MinIO passwords in `.env`. Never commit `.env`.

### 4. Start PostgreSQL, Qdrant, and MinIO

```powershell
docker compose up -d
```

### 5. Install Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The first embedding operation downloads the configured local embedding model.

### 6. Run tests

```powershell
pytest -q
```

### 7. Start the API

```powershell
uvicorn app.main:app --reload
```

Health check:

```text
GET http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

## First RBI end-to-end test

With the API running, execute:

```powershell
python scripts/rbi_smoke_test.py
```

By default this ingests the official RBI Bulletin site and asks a broad question about the retrieved economic content.

You can also supply a specific official RBI HTML/PDF URL and your own question:

```powershell
python scripts/rbi_smoke_test.py "https://<official-rbi-url>" "What does this document say about inflation?"
```

## API endpoints

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

Current answers use **extractive grounded mode**. The system selects statements from the retrieved source evidence rather than asking a generative model to invent an answer. Each response includes evidence, source URL, retrieval score, source authority level, and retrieval timestamp.

## Data safety

Do not commit API keys, passwords, downloaded PDFs, databases, embeddings, or large financial datasets. `.gitignore` excludes these from Git. Raw documents remain in private storage.

## Important design rule

New internet material is not automatically treated as truth. Source identity and provenance are preserved first. Later phases will add claim extraction, cross-source verification, contradiction handling, temporal versioning, and knowledge promotion states such as `candidate`, `verified`, `trusted`, `superseded`, and `rejected`.

## Next milestone

After this Phase 1 branch is locally verified:

`RBI ingestion -> structured claim extraction -> publication/effective dates -> verification -> PostgreSQL facts -> improved grounded answers`

Only after that will scheduled continuous learning be enabled.
