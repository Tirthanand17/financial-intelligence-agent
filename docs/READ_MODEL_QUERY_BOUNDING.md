# Read-Model Query Bounding

## Purpose

This post-roadmap hardening milestone reduces avoidable full-history materialization in high-use read-only intelligence surfaces without changing evidence, claim, trust, ingestion, or scheduler semantics.

The project remains evidence-first and fail-closed. This work is a query-shaping optimization only; it does not delete history, summarize away evidence, or introduce approximate/fuzzy results.

## Intelligence Digest

The bounded digest now pushes its 1–30 day window into SQL:

- document recency is filtered by persisted `retrieved_at` in the database;
- the exact recent-document count is computed with `COUNT(*)`;
- at most the requested 1–50 document rows are materialized for display;
- claim temporal scope is filtered in SQL using the existing precedence rule: `effective_date` when present, otherwise `publication_date`;
- inactive rejected/superseded current claims are filtered before materialization;
- the existing evidence-text quality gate still runs in application code so policy behavior is unchanged.

This optimization does not reinterpret retrieval time as publication time. Missing claim dates remain missing.

## Evidence Timeline

Timeline entity, metric, and source filters are now applied directly in SQL before claim objects are materialized. Filter-control facets are fetched using distinct-column queries instead of loading the complete unfiltered claim history solely to calculate available values.

The timeline still preserves all existing chronological, supersession, conflict, quality, and undated semantics.

## Evidence Change Detection

When an operator supplies a source or entity filter, that scope is now pushed into the claim query. The global persisted-claim count remains available through a lightweight SQL count so existing diagnostics retain their meaning.

Unfiltered change detection still needs the complete applicable history because adjacent historical observations are required to detect factual changes correctly. This milestone deliberately does not truncate that history or introduce an arbitrary row cutoff, because doing so could silently hide a predecessor and change the detected event set.

## Why no destructive shortcut

The system must not gain speed by:

- deleting or compacting retained evidence;
- dropping historical claims or supersession edges;
- replacing exact comparisons with fuzzy/approximate comparisons;
- inventing dates;
- reducing verification/trust safeguards;
- weakening source provenance;
- changing scheduler cadence.

Where full history is semantically necessary, it remains available. Future large-scale optimization can use indexed keyset/window queries or precomputed read models only after exact-equivalence tests prove that evidence semantics are preserved.

## Safety

No database schema migration is applied by this milestone. No PostgreSQL/B2/Qdrant data is mutated. No new paid infrastructure is introduced. Trust promotion remains disabled and all ingestion/scheduler gates are unchanged.
