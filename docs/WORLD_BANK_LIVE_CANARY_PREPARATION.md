# World Bank Live Canary Preparation

## Status

Prepared but **not executed** by this milestone.

The production source set remains RBI, SEBI, NSE, and MoSPI. No World Bank monitor is added and the recurring scheduler is unchanged.

The initial seven-day scheduler observation window is now formally closed through PR #68 with `FINAL: ROLLOUT-CLOSEOUT-READY`. That removes the rollout-history blocker but does not itself execute or activate World Bank.

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

## One-shot GitHub Actions execution gate

For the first live canary, `.github/workflows/world-bank-live-canary-once.yml` provides a temporary secret-safe execution environment using the repository's already-configured cloud secrets and capacity variables.

It does not add a schedule or `workflow_dispatch` surface. The job can start only from a newly created PR conversation comment when every condition below is true:

- the comment is on PR #68, the recorded rollout-closeout PR;
- the comment author is exactly `Tirthanand17`;
- the comment body exactly equals `/run-world-bank-live-canary-2026-09-20`;
- the workflow is already present on default-branch `main`.

The workflow has read-only repository contents permission, serial non-cancelling concurrency, and a fixed canary contract:

- indicator `NY.GDP.MKTP.KD.ZG`;
- exactly 3 recent observations maximum;
- explicit network/write/confirmation flags;
- all normal monitoring/auto-ingest/trust gates false;
- fail-closed production readiness before and after the write;
- zero structured claims required;
- reconciled `indexed` or idempotent `already_indexed` persistence state required;
- valid SHA-256, document id, and bounded observation/chunk reconciliation required.

The workflow is temporary. After the first controlled execution and evidence review, remove this one-shot trigger in a cleanup PR rather than leaving an unnecessary live-write command surface in the repository.

## Pre-write safety gates

Before network activity/persistence the runner requires:

- `TRUST_PROMOTION_ENABLED=false`;
- `SOURCE_MONITORING_ENABLED=false`;
- `SOURCE_AUTO_INGEST_ENABLED=false`;
- measured Supabase, B2, and Qdrant capacity all inside the approved project ceilings.

Missing/unknown/low/exhausted capacity blocks the canary.

The one-shot workflow additionally verifies the recorded rollout closeout and requires current production readiness to end in `FINAL: PASS-READ-ONLY` before the canary command is allowed to run.

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

A successful live canary would establish that one bounded World Bank provider response can be downloaded, preserved and reconciled end-to-end under the current evidence policy.

It would **not** by itself mean that:

- World Bank is activated in daily monitoring;
- its annual observations are eligible as current dated claims;
- trust promotion is enabled;
- the scheduler should process World Bank automatically;
- IMF or any other international source is approved.

Those require separate review/activation decisions.

## Validation

Tests require the explicit network/write/confirmation triplet, block unsafe runtime gates, enforce pre/post capacity checks, verify the exact downloaded byte object and SHA are passed to persistence, and reject any unexpected structured-claim creation.

Separate workflow-safety tests require the temporary execution workflow to remain comment-triggered, owner/PR/command locked, serial, minimally permissioned, fixed to the bounded World Bank contract, and separate from normal source monitoring.