# World Bank Live Canary Preparation

## Status

Prepared but **not executed** by this milestone.

The production source set remains RBI, SEBI, NSE, and MoSPI. No World Bank monitor is added and the recurring scheduler is unchanged.

## Purpose

This milestone prepares the smallest possible controlled live validation for the existing World Bank Indicators API candidate. It is intentionally separate from source activation.

The canary is designed to prove one real provider response can pass the already-reviewed bounded API contract and the existing exact-byte PostgreSQL/B2/Qdrant persistence path without inventing claim dates or creating structured claims.

## Manual execution contract

The canary CLI is:

`python scripts/world_bank_live_canary.py`

Execution is blocked unless all three explicit approvals are supplied at runtime:

- `--allow-network`
- `--allow-write`
- `--confirm WORLD_BANK_LIVE_CANARY`

The indicator must be one of the fixed reviewed codes and `recent_observations` is bounded to 1–5.

This runner is not imported by the recurring scheduler or live monitor registry.

## Pre-write safety gates

Before network activity/persistence the runner requires:

- `TRUST_PROMOTION_ENABLED=false`;
- `SOURCE_MONITORING_ENABLED=false`;
- `SOURCE_AUTO_INGEST_ENABLED=false`;
- measured Supabase, B2, and Qdrant capacity all inside the approved project ceilings.

Missing/unknown/low/exhausted capacity blocks the canary.

## Network contract

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

## Persistence and reconciliation

The exact bytes returned by the validated request are passed directly to `persist_world_bank_payload` with their SHA-256.

The existing persistence path then:

1. validates the same bounded URL contract again;
2. verifies the expected SHA-256;
3. parses the exact accepted bytes;
4. preserves the exact JSON bytes in private B2;
5. replays the B2 object and verifies the hash;
6. writes provenance/document metadata in PostgreSQL;
7. writes deterministic evidence chunks to Qdrant;
8. checks document point reconciliation;
9. leaves the document `reconciliation_required` on incomplete reconciliation rather than deleting evidence;
10. creates **zero structured claims** because annual observation periods are not publication/effective dates in the current claim model.

After the write, capacity is measured again. If a safety ceiling is crossed, the run fails closed while retaining the already-preserved evidence.

## What success would mean

A successful manual live canary would establish that one bounded World Bank provider response can be downloaded, preserved and reconciled end-to-end under the current evidence policy.

It would **not** by itself mean that:

- World Bank is activated in daily monitoring;
- its annual observations are eligible as current dated claims;
- trust promotion is enabled;
- the scheduler should process World Bank automatically;
- IMF or any other international source is approved.

Those require separate review/activation decisions.

## Why it is not executed yet

The initial seven-day four-source scheduler observation must be fully closed out first. Preparing this runner does not bypass that operational gate.

## Validation

Tests require the explicit network/write/confirmation triplet, block unsafe runtime gates, enforce pre/post capacity checks, verify the exact downloaded byte object and SHA are passed to persistence, and reject any unexpected structured-claim creation.
