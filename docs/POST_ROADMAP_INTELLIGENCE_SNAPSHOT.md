# Post-Roadmap Milestone — Read-Only Intelligence Snapshot

This milestone improves the usefulness of the Financial Intelligence Agent without changing the validated ingestion, monitoring, evidence-preservation, verification, trust, or scheduler boundaries established by Phases 1–17 and the approved operational rollout.

It is intentionally **not** a new numbered phase.

## Goal

Turn already-persisted evidence and structured claims into a concise operator-facing intelligence view while preserving the project's evidence-first model.

The snapshot does not generate new facts, infer market direction, make trading recommendations, alter claim state, promote trust, fetch new sources, or write to PostgreSQL, Backblaze B2, or Qdrant.

## Protected endpoint

```text
GET /dashboard/intelligence
```

The endpoint uses the same HTTP Basic authentication as the private dashboard and sends `Cache-Control: no-store`.

Optional query parameters:

```text
source_id=<trusted source id>
limit=1..50
```

Examples:

```text
/dashboard/intelligence
/dashboard/intelligence?source_id=rbi&limit=10
```

## Output

The response organizes persisted state into:

- total document and claim counts for the requested scope;
- claim-state counts;
- per-source document/claim coverage;
- active quality-safe structured claims;
- candidate vs verified/trusted counts;
- current conflicted claims requiring attention;
- the number of legacy claims hidden by the existing Phase 16 quality floor;
- recent preserved documents; and
- an explicit interpretation/safety block.

The latest-claim list excludes `rejected` and `superseded` rows from the active view but does not delete or rewrite them. Legacy parser noise remains preserved historically and is only excluded from the surfaced intelligence view using the same narrow Phase 16 quality predicate already enforced by verification/trust logic.

## Safety properties

- read-only database access;
- no B2 writes;
- no Qdrant writes;
- no scheduler changes;
- no source-monitor changes;
- no trust promotion;
- no LLM-generated facts;
- no market forecast or trading signal;
- no evidence deletion;
- no hidden mutation of historical claim rows.

Candidate claims are explicitly identified as source-grounded but not independently verified. Conflicted claims are surfaced as attention items instead of being resolved by guesswork.

## Why this milestone comes next

The system already has a validated data plane: trusted ingestion, provenance, exact-byte evidence, vector indexing, structured claims, source independence, monitoring, bounded recurring collection, and operational integrity checks. The next useful step is therefore not faster ingestion or looser automation; it is making the preserved intelligence state easier to inspect and reason about without weakening the trust model.
