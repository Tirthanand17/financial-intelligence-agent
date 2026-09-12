# Phase 6 Controlled Validation

Phase 6 validates the monitoring prerequisites against the real configured cloud environment without enabling scheduled monitoring, queue processing, auto-ingestion, or trust promotion.

## One-shot validation command

Run only from the configured private Codespace/environment that already contains the project's existing `.env` values:

```bash
python scripts/phase6_controlled_validation.py --allow-network
```

The `--allow-network` flag is deliberately required. Without it, the script exits before creating cloud clients or making any network request.

The validation is read-only. It:

1. measures PostgreSQL database size with `pg_database_size(current_database())`;
2. sums Backblaze B2 S3 object-size metadata without downloading object bodies;
3. reads the Qdrant collection point count;
4. applies only explicitly configured monitoring ceilings (missing ceilings remain `UNKNOWN` and fail closed);
5. downloads the explicitly registered monitor feed through the existing trusted downloader;
6. parses only a bounded number of allow-listed RSS/Atom entries; and
7. reports aggregate counts, content SHA-256, and latest feed publication date when available.

It does **not**:

- create or update monitor state/run rows;
- write discovery queue rows;
- follow or ingest discovered item URLs;
- write Backblaze objects;
- write Qdrant points;
- create/update structured claims;
- enable source monitoring;
- enable automatic ingestion;
- enable trust promotion; or
- perform any financial action.

## Expected safe gate state

For this validation, the normal expected configuration is still:

```text
SOURCE_MONITORING_ENABLED=false
SOURCE_AUTO_INGEST_ENABLED=false
TRUST_PROMOTION_ENABLED=false
```

The manual diagnostic does not require changing these switches because its own `--allow-network` flag is the one-run consent boundary and the diagnostic itself has no write path.

## Interpreting capacity

A successful usage measurement does not mean automatic monitoring is allowed. The capacity decision remains fail-closed until deliberately selected ceilings are configured for all three services.

Do not copy guessed provider limits into the project. Before enabling any scheduler, confirm the actual applicable free-plan/account limits and choose internal ceilings below them with enough safety margin to avoid surprise charges or quota exhaustion.

## Next step after a successful probe

Review the output first. Only after the three usage measurements are known, the registered feed is safely reachable, and explicit no-cost ceilings are selected should the project consider a controlled persisted monitor run. Scheduled monitoring and auto-ingestion remain separate later decisions.
