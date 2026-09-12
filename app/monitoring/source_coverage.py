from dataclasses import dataclass

from app.monitoring.models import MonitorDefinition
from app.sources.registry import AuthorityLevel, SourceDefinition


@dataclass(frozen=True, slots=True)
class SourceCoverageRow:
    source_id: str
    source_name: str
    authority_level: AuthorityLevel
    category: str
    country: str | None
    enabled: bool
    monitor_count: int
    monitor_ids: tuple[str, ...]

    @property
    def monitored(self) -> bool:
        return self.monitor_count > 0


def build_source_coverage(
    sources: tuple[SourceDefinition, ...],
    monitors: tuple[MonitorDefinition, ...],
) -> tuple[SourceCoverageRow, ...]:
    rows: list[SourceCoverageRow] = []
    for source in sources:
        source_monitors = tuple(
            monitor.monitor_id
            for monitor in monitors
            if monitor.source_id == source.source_id and monitor.enabled
        )
        rows.append(
            SourceCoverageRow(
                source_id=source.source_id,
                source_name=source.name,
                authority_level=source.authority_level,
                category=source.category,
                country=source.country,
                enabled=source.enabled,
                monitor_count=len(source_monitors),
                monitor_ids=source_monitors,
            )
        )
    return tuple(rows)


def primary_india_monitoring_gaps(
    coverage: tuple[SourceCoverageRow, ...],
) -> tuple[SourceCoverageRow, ...]:
    return tuple(
        row
        for row in coverage
        if row.enabled
        and row.country == "IN"
        and row.authority_level == AuthorityLevel.A
        and not row.monitored
    )
