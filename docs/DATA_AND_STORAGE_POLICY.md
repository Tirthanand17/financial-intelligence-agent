# Data and Storage Policy

## Non-negotiable principle

The Financial Intelligence Agent must not reduce knowledge quality, source coverage, provenance, historical retention, research depth, or evaluation quality merely to save storage on the developer's local PC.

When local disk is constrained, storage and compute must move to private cloud services or other remote infrastructure. Data quality is the priority; local storage usage is not.

## Local PC policy

The local PC should contain only lightweight development artifacts when needed:

- Git working copy
- source code and configuration templates
- optional small caches

The local PC should not be the authoritative store for:

- raw PDFs, reports, books, magazines, research papers, filings, or datasets
- vector embeddings
- PostgreSQL databases
- large market/economic time series
- archived source versions
- model weights
- large temporary processing files

Target local footprint: normally below 2 GB and never intentionally above 10 GB without explicit approval.

## Cloud-first storage roles

- GitHub Private: source code, tests, documentation, schemas, workflows
- GitHub Codespaces / Actions: development and CI compute
- Hosted PostgreSQL (Supabase initially): structured provenance, entities, claims, dates, versions, verification states
- Qdrant Cloud: vector storage, semantic retrieval, server-side/cloud inference where supported
- S3-compatible private object storage (Cloudflare R2 initially): original source documents and immutable evidence

## Data-retention policy

Do not delete or omit authoritative knowledge simply because a free tier is approaching capacity. Instead:

1. measure storage growth;
2. deduplicate exact copies using hashes;
3. compress or tier cold data without losing source fidelity;
4. move older data to another private free/low-cost cloud tier when appropriate;
5. preserve metadata and retrieval pointers;
6. keep historical versions when facts change;
7. never silently replace old economic or market facts with new values.

## Source-quality policy

Storage constraints must never cause the system to prefer lower-quality sources. Priority remains:

1. official regulators, exchanges, government and central banks;
2. international official organizations;
3. primary company filings and reports;
4. peer-reviewed/open research;
5. reputable secondary sources;
6. discovery-only sources such as Wikipedia, blogs, and social media.

Lower-tier sources may help discover topics but must not override authoritative evidence.

## Portability policy

All major data layers must remain portable:

- Git -> any Git provider
- PostgreSQL -> standard PostgreSQL dump/restore
- S3-compatible objects -> another S3-compatible provider or self-hosted object storage
- Qdrant -> Qdrant snapshots/export or a compatible migration workflow
- raw documents -> standard file formats

No service should become a single point of irreversible vendor lock-in.

## Capacity behavior

If a free cloud tier fills up, the system should stop new ingestion safely and alert/report the capacity issue rather than deleting trusted data, truncating documents, lowering retention, or silently skipping evidence.

## Project goal

The system is intended to grow into a continuously learning financial and economic intelligence platform. Infrastructure choices should therefore optimize for correctness, provenance, retention, privacy, portability, and scalable cloud storage before local convenience.
