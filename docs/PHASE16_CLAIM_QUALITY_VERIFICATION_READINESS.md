# Phase 16 — Claim Quality and Verification Readiness

Phase 15 closed the India Authority-A monitoring gap and proved controlled exact-byte canaries for SEBI, NSE, and MoSPI. Phase 16 does **not** turn on trust promotion. The first Phase 16 objective is to prevent obvious parser noise and page metadata from entering the structured-claim layer, then measure whether the remaining persisted evidence is suitable for conservative cross-source verification.

## Safety invariants

The normal runtime gates remain disabled during Phase 16 hardening:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- no historical source document, object-store evidence, vector chunk, or claim row is silently deleted;
- no legacy claim is rewritten merely because a newer quality rule would reject it;
- quality rules act on derived structured candidates, not on preserved source evidence.

## First checkpoint — narrow quality floor

The eligibility layer now rejects only high-confidence non-fact output classes observed during real Phase 15 canaries:

- page metadata labels such as `Posted On`, `Release ID`, `Visitor Counter`, `Date`, `Phone no`, and `Scrip Code`;
- one- or two-letter parser fragments such as `r.` and `i r.`;
- month/year heading fragments such as `SEP 2026 2`;
- schedule prose misread as key/value data when the evidence line contains multiple clock times.

The existing subject-attribution rule for `Policy Repo Rate` remains unchanged and is applied after the quality floor.

## Legacy evidence policy

Existing candidate claims remain preserved. `scripts/phase16_claim_quality_readiness.py` performs a read-only inventory of legacy quality debt and claim-state counts. It reports examples with bounded output but performs no state transition, deletion, trust promotion, or evidence mutation.

## Advancement criteria

Phase 16 may advance only after the full test suite is green, the read-only quality audit is understood, controlled preflights show materially cleaner eligible-claim output, and verification/trust readiness is still fail-closed. Automatic `TRUSTED` promotion is not allowed merely because a claim passes the quality floor; independent corroboration and all existing trust-policy requirements still apply.
