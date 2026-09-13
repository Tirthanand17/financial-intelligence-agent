from app.monitoring.registry import MONITORS
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.registry import TRUSTED_SOURCES


def test_current_source_coverage_identifies_primary_india_gaps() -> None:
    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    by_id = {row.source_id: row for row in coverage}

    assert by_id["rbi"].monitored is True
    assert by_id["rbi"].monitor_ids == ("rbi-press-releases-rss",)
    assert by_id["sebi"].monitored is True
    assert by_id["sebi"].monitor_ids == ("sebi-rss",)

    gaps = primary_india_monitoring_gaps(coverage)
    assert tuple(row.source_id for row in gaps) == ("mospi",)


def test_coverage_keeps_secondary_sources_visible_without_promoting_them() -> None:
    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    by_id = {row.source_id: row for row in coverage}

    assert by_id["world_bank"].authority_level.value == "B"
    assert by_id["imf"].authority_level.value == "B"
    assert by_id["ddnews"].authority_level.value == "B"
    assert by_id["akashvani"].authority_level.value == "B"
