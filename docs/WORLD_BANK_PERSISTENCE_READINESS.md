# World Bank Exact-Byte Persistence Readiness

## Purpose

This post-roadmap milestone prepares a preservation-first persistence path for the already-reviewed World Bank Indicators API candidate without activating the source.

It does **not** add a World Bank monitor, change the daily scheduler, perform a provider network fetch, or mark the candidate live-canary ready.

## Scope

The implementation accepts only already-acquired bytes for the bounded World Bank candidate contract:

- source: `world_bank`;
- country: India (`IND`);
- allow-listed indicator codes only;
- 1–5 recent observations;
- HTTPS `api.worldbank.org` URL built from the reviewed adapter contract;
- `application/json` evidence.

Both the requested URL and final URL are revalidated against the exact bounded path/query contract before storage writes.

## Exact-byte preservation

Before persistence, the service:

1. computes SHA-256 over the exact accepted JSON bytes;
2. optionally compares it with a caller-supplied expected SHA-256;
3. parses the same bytes through the World Bank adapter;
4. rejects adapter output if it does not retain the exact original byte string.

For a new document it then:

1. stores the exact JSON bytes in private B2-compatible object storage;
2. reads the object back immediately;
3. recomputes SHA-256 over the replayed bytes;
4. blocks on any mismatch;
5. creates the PostgreSQL document row as `reconciliation_required`;
6. indexes deterministic evidence chunks in Qdrant;
7. checks that all deterministic document point IDs are retrievable;
8. changes the document status to `indexed` only after the point-count check passes.

No preserved evidence is deleted when reconciliation fails.

## JSON object naming

`application/json` evidence now receives a `.json` object-key suffix. The suffix is metadata convenience only; the exact original bytes remain unchanged.

## Temporal safety

World Bank `date` is an **observation period**, not a claim publication date or effective date. Response-level `lastupdated` is source metadata and is also not treated as a claim publication/effective date.

The deterministic vector evidence therefore labels these concepts explicitly. The persistence path creates **zero structured claims**. A separately reviewed temporal representation is required before World Bank observations can enter the structured claim lifecycle.

## Reconciliation / retry behavior

Document SHA-256 remains the idempotency key used by the existing document store. On a retry:

- an already indexed document is returned only after raw-object replay and expected Qdrant-point checks pass;
- an incomplete document is left or reset to `reconciliation_required` and its deterministic points may be safely re-upserted;
- a raw-evidence hash mismatch fails closed;
- a Qdrant mismatch fails closed while the preserved evidence and PostgreSQL reconciliation marker remain available for diagnosis.

## Readiness semantics

The international source readiness model now distinguishes:

- `persistence_path_implemented`;
- `offline_exact_byte_contract_validated`;
- `exact_byte_reconciliation_validated`;
- `bounded_live_canary_passed`.

The first two are true for the World Bank candidate after this milestone. The latter two remain false until a controlled live cross-store canary is executed against actual provider bytes.

Therefore this milestone **does not make World Bank activation-ready**.

## Rollout gate

The existing RBI / SEBI / NSE / MoSPI live source set remains unchanged. The initial scheduled-rollout closeout gate must finish successfully before a World Bank live canary or activation is considered.

## Tests

Offline regression tests cover:

- exact SHA preflight failure before writes;
- exact raw-byte replay verification;
- JSON object-key preservation;
- deterministic evidence chunks with explicit observation-period semantics;
- zero structured-claim creation;
- successful B2/PostgreSQL/Qdrant-path reconciliation using isolated fakes;
- idempotent duplicate retry;
- reconciliation-required state on vector mismatch;
- bounded URL/query validation;
- timezone-aware retrieval timestamps;
- readiness reporting that remains blocked on live reconciliation/canary requirements.
