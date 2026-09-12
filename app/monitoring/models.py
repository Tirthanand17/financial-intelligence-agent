from dataclasses import dataclass
from enum import StrEnum


class CapacityState(StrEnum):
    OK = "ok"
    LOW = "low"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class MonitorState(StrEnum):
    READY = "ready"
    DISABLED = "disabled"
    PAUSED_CAPACITY = "paused_capacity"
    PAUSED_ERROR = "paused_error"


class MonitorRunOutcome(StrEnum):
    SUCCESS = "success"
    NO_CHANGE = "no_change"
    PAUSED_CAPACITY = "paused_capacity"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ServiceCapacity:
    """Non-secret capacity status for one required cloud service."""

    service: str
    state: CapacityState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    allow_ingestion: bool
    reason: str
    blocking_services: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MonitorDefinition:
    """One explicitly configured research-source monitor.

    Monitors are source-specific and bounded. Phase 5 does not permit generic
    open-web crawling or financial execution actions.
    """

    monitor_id: str
    source_id: str
    url: str
    interval_minutes: int
    enabled: bool = False
    max_new_documents_per_run: int = 10

    def __post_init__(self) -> None:
        if not self.monitor_id.strip():
            raise ValueError("monitor_id is required")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if not self.url.startswith("https://"):
            raise ValueError("monitor URL must use HTTPS")
        if self.interval_minutes < 60:
            raise ValueError("monitor interval must be at least 60 minutes")
        if self.max_new_documents_per_run < 1:
            raise ValueError("max_new_documents_per_run must be positive")
        if self.max_new_documents_per_run > 100:
            raise ValueError("max_new_documents_per_run must remain bounded")


@dataclass(frozen=True, slots=True)
class MonitorDecision:
    state: MonitorState
    reason: str
    blocking_services: tuple[str, ...] = ()
