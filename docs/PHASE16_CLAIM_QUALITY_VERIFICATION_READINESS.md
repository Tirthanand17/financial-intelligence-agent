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

Legitimate short financial abbreviations and metrics such as OI, PE, P/E, CRR, SLR, MCLR and G-Sec yield remain eligible. The existing subject-attribution rule for `Policy Repo Rate` is applied after the quality floor.

## Verification and trust boundary

The same narrow quality predicate is now enforced when comparing evidence. A quality-failed legacy row is preserved in its current state, but it cannot independently verify a clean claim, create a conflict against a clean claim, corroborate a primary claim for trust promotion, or itself advance from VERIFIED to TRUSTED.

This does not weaken the existing independence, authority-level, temporal-scope, entity-attribution, and conflict checks. It only prevents known parser noise from being counted as evidence.

## Live read-only validation

The final Phase 16 live audit ran with all three global gates false and reviewed 37 active claims. All 37 remained `candidate`; 15 legacy quality issues were inventoried without mutation: 7 metadata metrics, 1 month-heading fragment, 5 schedule-time fragments, and 2 short parser fragments. There were 0 VERIFIED/TRUSTED claims, 0 unreviewed promotable claims, 0 verification events, and 0 trust events. Both Phase 16 audit scripts returned `PASS-READ-ONLY`.

Controlled read-only pending preflights then exercised the new quality floor on fresh official evidence. The NSE preflight validated one first-party PDF (351050 bytes, SHA-256 `d81b72aaefa9e4565fa130091147991cba54908fb7b5bd55aea683dad9fcce92`) with 3 eligible claims and no writes. The MoSPI preflight validated one first-party PDF (341138 bytes, SHA-256 `2289bc74eb2a598252ca0ed9e08cf29233daf6f02af856485f3757dcd2382baf`) with 0 eligible claims and no writes. This demonstrates that the quality floor can suppress non-fact output without changing preserved source evidence.

## Read-only audits

`scripts/phase16_claim_quality_readiness.py` inventories legacy quality debt and claim-state counts without changing any row. `scripts/phase16_closeout_readiness.py` additionally fails closed if a quality-failed row is already VERIFIED/TRUSTED, if a real persisted claim is currently promotable and therefore requires controlled review, if any trust-promotion event exists while the gate is expected off, or if any global automation/trust gate is enabled.

## Closeout

Phase 16 closeout criteria are satisfied: the full local suite passed with 334 tests and 2 pre-existing deprecation warnings, branch and pull-request CI are green, both live read-only audits passed, and fresh NSE/MoSPI preflights preserved zero-write behavior while applying the quality floor. No genuine promotable persisted claim currently exists, so no trust canary is authorized and `TRUST_PROMOTION_ENABLED` remains false.
