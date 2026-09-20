# World Bank Live Canary Record

## Status

The first bounded World Bank live canary was **executed successfully on 20 September 2026** after the initial seven-day scheduler rollout was formally closed.

The production source set remains RBI, SEBI, NSE, and MoSPI at this stage. The successful canary does **not** itself activate World Bank in recurring monitoring, and it does not change scheduler cadence or trust policy.

The temporary one-shot GitHub Actions trigger used for the live canary is removed by the same cleanup milestone that records this result, so an unnecessary live-write command surface is not left behind.

## Executed canary

GitHub Actions run:

- run id: `35503947233`
- job id: `106060458340`
- audited `main` commit: `5fb743f40ae0f25c8bc3b16adbb5c324a1c916dd`
- indicator: `NY.GDP.MKTP.KD.ZG`
- requested recent observations: `3`
- result status: `indexed`
- document id: `fe64eb55-0f96-4698-a53b-35fe10023769`
- SHA-256: `98acdb9979bafba647545425d085193a2c5aec912dbc8f5f088120c394f67fe2`
- Qdrant/evidence chunks: `3`
- structured claims created: `0`
- accepted annual observation periods: `2025`, `2024`, `2023`
- World Bank `lastupdated`: `2026-07-13` — retained only as source metadata, **not** a claim publication/effective date

The live response passed the fixed adapter scope, exact-byte validation, B2 replay/hash verification, PostgreSQL persistence and Qdrant reconciliation. No publication/effective date was inferred from annual observation periods or source metadata.

## Pre-write readiness

Immediately before the live canary:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- capacity allowed: true
- required live monitors ready: 4/4
- queue metadata anomalies: 0
- linked-document anomalies: 0
- documents: 43
- integrity failures: 0
- expected Qdrant points: 170
- actual Qdrant points: 170
- claims: 59
- orphan claims: 0
- quality-failed verified/trusted claims: 0
- trust events: 0
- final readiness: `FINAL: PASS-READ-ONLY`

## Post-write reconciliation

Immediately after the canary:

- all three normal global gates remained false;
- capacity remained allowed with no blockers;
- required live monitors remained ready: 4/4;
- queue metadata anomalies remained 0;
- linked-document anomalies remained 0;
- documents increased from 43 to 44;
- integrity failures remained 0;
- expected Qdrant points increased from 170 to 173;
- actual Qdrant points increased from 170 to 173;
- claims remained 59;
- orphan claims remained 0;
- quality-failed verified/trusted claims remained 0;
- trust events remained 0;
- final readiness remained `FINAL: PASS-READ-ONLY`.

This is the expected footprint for one World Bank JSON document containing three evidence chunks and zero structured claims.

## Idempotency evidence

The live canary was intentionally not repeated merely to prove idempotency because a second provider request could return different bytes and unnecessarily create a second legitimate evidence version.

The persistence implementation has a deterministic regression test that persists the same exact bytes twice and requires the second call to return `already_indexed`, reuse the same document id, avoid another Qdrant indexing call, keep one document row, and keep zero claim rows.

This preserves the one-live-write bound while still validating exact-byte idempotency in the persistence contract.

## Execution contract retained in code

The reusable CLI remains:

`python scripts/world_bank_live_canary.py`

Execution is blocked unless all three explicit approvals are supplied at runtime:

- `--allow-network`
- `--allow-write`
- `--confirm WORLD_BANK_LIVE_CANARY`

The indicator must be one of the fixed reviewed codes and `recent_observations` is bounded to 1–5. The runner is not imported by the recurring scheduler or live monitor registry.

## Safety contract

Before network activity/persistence the runner requires:

- `TRUST_PROMOTION_ENABLED=false`;
- `SOURCE_MONITORING_ENABLED=false`;
- `SOURCE_AUTO_INGEST_ENABLED=false`;
- measured Supabase, B2, and Qdrant capacity all inside the approved project ceilings.

Missing, unknown, low, or exhausted capacity blocks the canary.

The request is constructed only by the World Bank source adapter:

- HTTPS only;
- India only (`IND`);
- exact reviewed indicator codes only;
- `api.worldbank.org` must already be allow-listed;
- GET only;
- redirects are rejected;
- final URL must equal the requested bounded URL;
- JSON content type only;
- response size capped at 1 MiB;
- accepted bytes must successfully parse under the strict World Bank adapter before any write.

No arbitrary URL or host is accepted.

## Persistence and reconciliation contract

The exact accepted bytes are passed to `persist_world_bank_payload` with their SHA-256. The persistence path:

1. validates the bounded URL contract again;
2. verifies the expected SHA-256;
3. parses the exact accepted bytes;
4. preserves exact JSON bytes in private B2;
5. replays the B2 object and verifies the hash;
6. writes provenance/document metadata in PostgreSQL;
7. writes deterministic evidence chunks to Qdrant;
8. checks document point reconciliation;
9. leaves the document `reconciliation_required` on incomplete reconciliation rather than deleting evidence;
10. creates **zero structured claims** because annual observation periods are not publication/effective dates in the current claim model.

After a write, capacity is measured again. If a safety ceiling is crossed, the operation fails closed while retaining already-preserved evidence.

## What the successful canary proves

The result establishes that one bounded real World Bank provider response can be downloaded, preserved and reconciled end-to-end under the current evidence policy.

It does **not** by itself mean that:

- World Bank is activated in daily monitoring;
- annual observations are eligible as dated claims;
- trust promotion is enabled;
- the scheduler may increase cadence;
- IMF or another international source is approved.

A production activation, if adopted, must be a separate reviewed milestone with a bounded monitor/processing contract, unchanged trust policy, tests, CI, post-merge verification, and no weakening of the existing four production sources.