# Non-Destructive Recovery Rehearsal

## Purpose

This post-roadmap milestone extends recovery readiness into a deterministic, secret-free reconstruction manifest without provisioning a restore target or mutating production.

The rehearsal combines the existing live recovery-readiness checks with a document reconstruction inventory containing only safe fields: document ID, source ID, SHA-256, content type, chunk count, retrieval timestamp, and status. Private B2/S3 object keys are intentionally excluded.

## Rehearsal checks

The rehearsal fails closed unless all of these are true:

- the existing recovery-readiness report is safe;
- every preserved evidence object verifies against its stored SHA-256;
- Qdrant exactly reconciles with the expected point count;
- manifest document count matches the database inventory;
- manifest chunk total matches the Qdrant expectation;
- no private object-store keys are present in the manifest.

A SHA-256 digest is calculated over a canonical JSON representation of the secret-free manifest so two identical inventories produce the same digest.

## CLI

Run:

```bash
python scripts/recovery_rehearsal.py
```

Optional local output:

```bash
python scripts/recovery_rehearsal.py --output recovery-rehearsal.json
```

The command exits successfully only when every rehearsal check passes. The optional output is local to the runner/workspace; it does not write any cloud store.

## Restore sequence documented by the manifest

A real isolated drill would require separate operator-approved PostgreSQL, object-store, and Qdrant destinations. The expected sequence is database/history restore, exact raw-byte restoration with SHA verification, vector restoration/rebuild with exact point reconciliation, cross-table/history checks, and only then isolated validation.

## Important boundary

This rehearsal does **not** claim that a provider backup or isolated restore has occurred. Those require separate destinations and explicit operator approval. Production destinations must never be used for a destructive restore test.

The report explicitly keeps these fields false:

- `provider_backup_created`;
- `isolated_targets_provisioned`;
- `isolated_restore_executed`;
- `production_mutated`.

This is intentionally the maximum recovery drill that can be performed without provisioning or writing to isolated infrastructure.
