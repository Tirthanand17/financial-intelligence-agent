# Financial Intelligence Agent

Private, continuously learning financial and economic intelligence system.

## Phase 1 goal

Build a trustworthy local-first foundation that can ingest authorized public financial sources, preserve the original evidence, extract searchable knowledge, and answer questions with source provenance.

## Initial architecture

- **FastAPI** — application/API layer
- **PostgreSQL** — structured facts, entities, events, provenance
- **Qdrant** — semantic/vector retrieval
- **MinIO** — raw documents and evidence storage
- **Docker Compose** — local infrastructure

## Trusted source registry

The first registry includes RBI, SEBI, NSE, MoSPI, World Bank, and IMF. Ingestion is not yet automated; sources are added deliberately and verified before continuous learning is enabled.

## Run locally

1. Install Python 3.11+ and Docker Desktop.
2. Copy `.env.example` to `.env` and replace placeholder credentials.
3. Start infrastructure:

```bash
docker compose up -d
```

4. Create a Python virtual environment and install dependencies:

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

5. Start the API:

```bash
uvicorn app.main:app --reload
```

6. Verify:

```text
GET http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Data safety

Do not commit API keys, passwords, downloaded PDFs, databases, embeddings, or large financial datasets. These are excluded through `.gitignore` and should live in private storage.

## Next milestone

Implement the first RBI document ingestion pipeline:

`trusted URL -> download -> MinIO -> text extraction -> chunking -> embeddings -> Qdrant -> provenance -> question answering`
