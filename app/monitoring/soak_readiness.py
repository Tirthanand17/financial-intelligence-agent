from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReadOnlySoakSample:
    documents: int
    claims: int
    verification_events: int
    trust_events: int
    discoveries: int
    monitor_runs: int
    monitor_states: int
    backblaze_b2_bytes: int | None
    qdrant_points: int | None
    capacity_allows_ingestion: bool
    rss_bytes: int


@dataclass(frozen=True, slots=True)
class ReadOnlySoakDecision:
    passed: bool
    blockers: tuple[str, ...]
    rss_growth_bytes: int


def assess_read_only_soak(
    samples: tuple[ReadOnlySoakSample, ...],
    *,
    max_rss_growth_bytes: int,
) -> ReadOnlySoakDecision:
    if len(samples) < 2:
        return ReadOnlySoakDecision(
            passed=False,
            blockers=("soak:insufficient_samples",),
            rss_growth_bytes=0,
        )
    if max_rss_growth_bytes < 0:
        raise ValueError("max_rss_growth_bytes cannot be negative")

    blockers: list[str] = []
    baseline = samples[0]
    stable_fields = (
        "documents",
        "claims",
        "verification_events",
        "trust_events",
        "discoveries",
        "monitor_runs",
        "monitor_states",
        "backblaze_b2_bytes",
        "qdrant_points",
    )
    for sample in samples:
        if not sample.capacity_allows_ingestion:
            blockers.append("soak:capacity_not_safe")
        for field in stable_fields:
            if getattr(sample, field) != getattr(baseline, field):
                blockers.append(f"soak:{field}_changed")
    rss_growth = max(sample.rss_bytes for sample in samples) - baseline.rss_bytes
    if rss_growth > max_rss_growth_bytes:
        blockers.append("soak:rss_growth_exceeded")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ReadOnlySoakDecision(
        passed=not unique_blockers,
        blockers=unique_blockers,
        rss_growth_bytes=rss_growth,
    )
