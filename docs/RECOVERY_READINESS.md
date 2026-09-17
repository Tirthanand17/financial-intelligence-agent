# Recovery Readiness

This milestone adds a **read-only recovery readiness report**. It does not create or restore provider backups automatically.

## What the report verifies

Run:

```bash
python scripts/recovery_readiness_report.py
```

The command reads the current PostgreSQL metadata, preserved Backblaze B2 evidence, and Qdrant collection state and reports:

- row counts for core evidence, claim, verification/trust, monitor, and discovery tables;
- claim-state and monitor-state distributions;
- exact-byte SHA-256 verification for every preserved evidence object referenced by the database;
- expected Qdrant point count derived from persisted document chunk counts;
- actual Qdrant point count and reconciliation status;
- an overall `safe` result.

The command exits non-zero if evidence is missing/unreadable, a stored SHA-256 differs from the preserved bytes, Qdrant is unavailable, or expected/actual vector counts differ.

Provider exception details are deliberately not included in the output so credentials or sensitive endpoint information cannot leak through a readiness artifact.

An optional local manifest can be written with:

```bash
python scripts/recovery_readiness_report.py --output recovery/readiness.json
```

## What this is not

This report is **not** a Supabase/PostgreSQL backup, B2 bucket clone, or Qdrant snapshot. It is a consistency gate that should pass before a real backup/restore exercise.

A true disaster-recovery validation still requires an isolated target environment and explicit operator approval. Production evidence must never be deleted or rewritten simply to make a restore test easier.

## Restore-test acceptance criteria

Before calling disaster recovery validated, an isolated restore must prove all of the following:

1. database row counts and relationships reconcile with the source manifest;
2. every restored evidence object hashes to the persisted SHA-256;
3. restored Qdrant point count equals the expected chunk count;
4. claims remain linked to valid documents;
5. trust/verification/supersession history is preserved;
6. no production store was mutated during the exercise.

Until such an isolated restore is completed, the report explicitly states `provider_backup_created: false` and `isolated_restore_executed: false`.
