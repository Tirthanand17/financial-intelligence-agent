# Phase 16 — Claim Quality and Verification Readiness

Phase 15 closed the India Authority-A monitoring gap and proved controlled exact-byte canaries for SEBI, NSE, and MoSPI. Phase 16 does **not** turn on trust promotion. Its objective is to prevent obvious parser noise and page metadata from entering the structured-claim layer, then prove that verification and trust decisions cannot use quality-failed legacy rows as corroborating evidence.

## Safety invariants

The normal runtime gates remain disabled during Phase 16 hardening:

- `SOURCE_MONITORING_ENABLED=false`
- `SOURCE_AUTO_INGEST_ENABLED=false`
- `TRUST_PROMOTION_ENABLED=false`
- no historical source document, object-store evidence, vector chunk, or claim row is silently deleted;
- no legacy claim is rewritten merely because a newer quality rule would reject it;
- quality rules act on derived structured candidates, not on preserved source evidence.

## Narrow structured-claim quality floor

The eligibility layer rejects only high-confidence non-fact output classes observed during real canaries:

- page metadata labels such as `Posted On`, `Release ID`, `Visitor Counter`, `Date`, `Phone no`, and `Scrip Code`;
- one- or two-letter parser fragments such as `r.` and `i r.`;
- month/year heading fragments such as `SEP 2026 2`;
- schedule prose misread as key/value data when the evidence line contains multiple clock times.

Legitimate financial metrics such as CRR, SLR, MCLR and G-Sec yield remain eligible. The existing subject-attribution rule for `Policy Repo Rate` is applied after the quality floor.

## Verification and trust boundary

The same narrow quality predicate is now enforced when comparing evidence. A quality-failed legacy row is preserved in its current state, but it cannot independently verify a clean claim, create a conflict against a clean claim, corroborate a primary claim for trust promotion, or itself advance from VERIFIED to TRUSTED.

This does not weaken the existing independence, authority-level, temporal-scope, entity-attribution, and conflict checks. It only prevents known parser noise from being counted as evidence.

## Read-only audits

`scripts/phase16_claim_quality_readiness.py` inventories legacy quality debt and claim-state counts without changing any row. `scripts/phase16_closeout_readiness.py` additionally fails closed if a quality-failed row is already VERIFIED/TRUSTED, if a real persisted claim is currently promotable and therefore requires controlled review, if any trust-promotion event exists while the gate is expected off, or if any global automation/trust gate is enabled.

## Advancement criteria

Phase 16 may close only after the full suite and CI are green and both read-only audits pass against the live database. If a genuine promotable claim is discovered, Phase 16 must stop for a separate controlled trust canary rather than enabling promotion globally. Legacy candidate-quality debt may remain preserved because source evidence must not be silently rewritten or deleted.
