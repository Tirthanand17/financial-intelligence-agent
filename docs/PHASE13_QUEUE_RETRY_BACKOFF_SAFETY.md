# Phase 13 — Queue Retry / Backoff Safety

Phase 12 proved that the real auto-ingestion gate can safely process one already-discovered pending research-evidence item. Before recurring monitoring and recurring ingestion are connected, Phase 13 closes a retry-safety gap in the pending queue.

## Why this phase exists

Operational ingestion failures intentionally leave a discovery in `pending` state with a symbolic `last_error_code`. Without a per-item retry schedule, a recurring worker could select that same failing row on every invocation. That could repeatedly hit a blocked or broken source and could let the oldest failed row interfere with useful newer work.

Phase 13 adds a conservative per-item retry policy:

- fresh pending rows with no prior error are immediately eligible;
- failed rows use exponential backoff based on the monitor interval;
- retry delay is capped at 24 hours;
- a first failed attempt on the current 60-minute RBI monitor waits 2 hours;
- incomplete failure metadata fails closed instead of guessing a retry time;
- fresh rows are selected before retries, so one backed-off failed row cannot starve untouched queue items;
- the exact-record processing path also enforces retry backoff, so controlled/recovery callers cannot accidentally bypass the protection.

## Safety boundary

This phase does not enable recurring ingestion. `TRUST_PROMOTION_ENABLED` remains off. The first live checkpoint is read-only and only inspects pending queue metadata. It performs no source download, no Backblaze B2 operation, no Qdrant operation, and no database write.

After the read-only live checkpoint passes, a later controlled checkpoint may validate the retry selector with real queue state before any recurring monitor-to-ingestion orchestration is enabled.
