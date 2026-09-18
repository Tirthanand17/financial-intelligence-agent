# Initial Scheduler Rollout Closeout Audit

## Purpose

The production scheduler was approved for an initial seven-day observation window before any cadence increase or new production source activation. This manual audit workflow turns that closeout into a reproducible fail-closed check rather than a visual/manual guess.

## Observation window

The required Asia/Kolkata calendar dates are:

- 2026-09-14
- 2026-09-15
- 2026-09-16
- 2026-09-17
- 2026-09-18
- 2026-09-19
- 2026-09-20

The workflow inspects only GitHub Actions runs whose event is `schedule`. A required day blocks closeout when no scheduled run exists or when any scheduled run for that IST date is non-successful.

Running the audit before all seven dates have a successful scheduled run therefore fails closed automatically.

## Current-state validation

Historical workflow success alone is not enough. After validating the seven observation days, the audit checks the live cloud state with the existing Phase 17 production-readiness script while all runtime mutation gates are false:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`

The audit requires `FINAL: PASS-READ-ONLY` before it can produce:

`FINAL: ROLLOUT-CLOSEOUT-READY`

## What READY means

`ROLLOUT-CLOSEOUT-READY` means only that the defined initial observation-history check and the current fail-closed readiness check passed.

It does **not** automatically:

- increase scheduler cadence;
- add World Bank, IMF, or another source to the live monitor registry;
- enable trust promotion;
- change source processing limits;
- modify evidence or claim states;
- approve a paid service;
- perform a live canary.

Any of those changes still require their own reviewed milestone.

## Safety and permissions

The workflow is `workflow_dispatch` only. It has `contents: read` and `actions: read` permissions, performs no ingestion/write command, and does not change repository issues, source configuration, cloud data, or deployment configuration.

The GitHub step summary records the seven IST dates, pass/block status, conclusions, and links to the corresponding scheduled runs so the closeout remains auditable.
