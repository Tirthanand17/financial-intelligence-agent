from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


_MAX_QUEUE_RETRY_BACKOFF_HOURS = 24


@dataclass(frozen=True, slots=True)
class DiscoveryRetryDecision:
    due: bool
    reason: str
    next_eligible_at: datetime | None


def _as_utc(value: datetime) -> datetime:
    """Normalize database/runtime timestamps to aware UTC.

    PostgreSQL returns timezone-aware values for the production schema, while
    SQLite used by tests may round-trip the same column as a naive datetime.
    Stored monitoring timestamps are UTC, so a naive value is interpreted as UTC
    rather than allowing a naive/aware comparison to fail at runtime.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def next_discovery_retry_at(
    *,
    interval_minutes: int,
    attempt_count: int,
    last_attempt_at: datetime | None,
    last_error_code: str | None,
) -> datetime | None:
    """Return the earliest safe retry time for one pending discovery.

    Brand-new pending rows have no error and are immediately eligible. Failed
    rows use exponential backoff based on the monitor interval, capped at 24
    hours. Incomplete failure metadata returns ``None`` so the caller can fail
    closed instead of guessing a retry time.
    """
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be positive")
    if attempt_count < 0:
        raise ValueError("attempt_count cannot be negative")

    if last_error_code is None:
        return None
    if attempt_count < 1 or last_attempt_at is None:
        return None

    base = timedelta(minutes=interval_minutes)
    multiplier = 2 ** min(attempt_count, 16)
    delay = min(
        base * multiplier,
        timedelta(hours=_MAX_QUEUE_RETRY_BACKOFF_HOURS),
    )
    return _as_utc(last_attempt_at) + delay


def assess_discovery_retry(
    *,
    now: datetime,
    interval_minutes: int,
    attempt_count: int,
    last_attempt_at: datetime | None,
    last_error_code: str | None,
) -> DiscoveryRetryDecision:
    """Decide whether a pending discovery may be attempted now.

    A row without an error is a fresh queue item and is immediately ready.
    Failed rows with incomplete retry metadata are deliberately blocked. This
    prevents a recurring worker from hammering a broken source because of an
    ambiguous database state.
    """
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be positive")
    if attempt_count < 0:
        raise ValueError("attempt_count cannot be negative")

    if last_error_code is None:
        return DiscoveryRetryDecision(
            due=True,
            reason="discovery_ready",
            next_eligible_at=None,
        )

    if attempt_count < 1 or last_attempt_at is None:
        return DiscoveryRetryDecision(
            due=False,
            reason="retry_metadata_incomplete",
            next_eligible_at=None,
        )

    eligible_at = next_discovery_retry_at(
        interval_minutes=interval_minutes,
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        last_error_code=last_error_code,
    )
    if eligible_at is None:
        return DiscoveryRetryDecision(
            due=False,
            reason="retry_metadata_incomplete",
            next_eligible_at=None,
        )

    now_utc = _as_utc(now)
    if now_utc < eligible_at:
        return DiscoveryRetryDecision(
            due=False,
            reason="retry_backoff",
            next_eligible_at=eligible_at,
        )
    return DiscoveryRetryDecision(
        due=True,
        reason="retry_due",
        next_eligible_at=eligible_at,
    )
