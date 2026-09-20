from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.monitoring.models import CapacityDecision, MonitorRunOutcome
from app.monitoring.world_bank import (
    WORLD_BANK_OPERATIONAL_INDICATOR,
    WORLD_BANK_OPERATIONAL_INTERVAL_MINUTES,
    WORLD_BANK_OPERATIONAL_MONITOR_ID,
    build_world_bank_operational_monitor,
    run_world_bank_operational_once,
)
from app.services.world_bank_live_canary import WorldBankLiveDownload
from app.services.world_bank_persistence import WorldBankPersistenceResult


NOW = datetime(2026, 9, 20, 10, 30, tzinfo=UTC)
SAFE = CapacityDecision(allow_ingestion=True, reason="capacity_safe")


class FakeSession:
    def __init__(self, state=None):
        self.state = state

    def get(self, _model, _key):
        return self.state


def _download() -> WorldBankLiveDownload:
    return WorldBankLiveDownload(
        source_url=(
            "https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG"
            "?format=json&mrv=3&per_page=3"
        ),
        final_url=(
            "https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG"
            "?format=json&mrv=3&per_page=3"
        ),
        content=b"exact-world-bank-json",
        content_type="application/json",
        sha256="a" * 64,
        retrieved_at=NOW,
    )


def _persistence(status: str) -> WorldBankPersistenceResult:
    return WorldBankPersistenceResult(
        document_id="doc-world-bank",
        status=status,
        sha256="a" * 64,
        object_key="raw/world_bank/a.json",
        chunk_count=3,
        claim_count=0,
        source_last_updated="2026-07-13",
        observation_periods=("2025", "2024", "2023"),
    )


def _run(*, session=None, status="indexed", after=SAFE, record_calls=None, **kwargs):
    session = session or FakeSession()
    record_calls = record_calls if record_calls is not None else []

    def download(indicator_code, *, recent_observations):
        assert indicator_code == WORLD_BANK_OPERATIONAL_INDICATOR
        assert recent_observations == 3
        return _download()

    def persist(**persist_kwargs):
        assert persist_kwargs["content"] == b"exact-world-bank-json"
        assert persist_kwargs["expected_sha256"] == "a" * 64
        return _persistence(status)

    def record_run(*args, **record_kwargs):
        record_calls.append((args, record_kwargs))

    return run_world_bank_operational_once(
        session,
        build_world_bank_operational_monitor(enabled=True),
        SAFE,
        now=NOW,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        allow_network=True,
        allow_write=True,
        download=download,
        persist=persist,
        capacity_after=lambda: after,
        record_run=record_run,
        **kwargs,
    )


def test_world_bank_operational_monitor_contract_is_daily_and_one_document_bounded() -> None:
    monitor = build_world_bank_operational_monitor(enabled=True)
    assert monitor.monitor_id == WORLD_BANK_OPERATIONAL_MONITOR_ID
    assert monitor.source_id == "world_bank"
    assert monitor.interval_minutes == WORLD_BANK_OPERATIONAL_INTERVAL_MINUTES == 1440
    assert monitor.max_new_documents_per_run == 1
    assert monitor.enabled is True
    assert "country/IND/indicator/NY.GDP.MKTP.KD.ZG" in monitor.url
    assert "mrv=3" in monitor.url


def test_world_bank_operational_monitor_requires_all_runtime_gates_before_network() -> None:
    monitor = build_world_bank_operational_monitor(enabled=True)
    called = False

    def download(*_args, **_kwargs):
        nonlocal called
        called = True
        return _download()

    with pytest.raises(RuntimeError, match="SOURCE_MONITORING_DISABLED"):
        run_world_bank_operational_once(
            FakeSession(),
            monitor,
            SAFE,
            now=NOW,
            source_monitoring_enabled=False,
            source_auto_ingest_enabled=True,
            trust_promotion_enabled=False,
            allow_network=True,
            allow_write=True,
            download=download,
            capacity_after=lambda: SAFE,
        )
    assert called is False

    with pytest.raises(RuntimeError, match="AUTO_INGEST_DISABLED"):
        run_world_bank_operational_once(
            FakeSession(),
            monitor,
            SAFE,
            now=NOW,
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=False,
            trust_promotion_enabled=False,
            allow_network=True,
            allow_write=True,
            download=download,
            capacity_after=lambda: SAFE,
        )
    assert called is False

    with pytest.raises(RuntimeError, match="TRUST_PROMOTION"):
        run_world_bank_operational_once(
            FakeSession(),
            monitor,
            SAFE,
            now=NOW,
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            trust_promotion_enabled=True,
            allow_network=True,
            allow_write=True,
            download=download,
            capacity_after=lambda: SAFE,
        )
    assert called is False


def test_world_bank_operational_monitor_cadence_guard_prevents_network() -> None:
    session = FakeSession(
        SimpleNamespace(last_checked_at=NOW, consecutive_failures=0)
    )
    called = False

    def download(*_args, **_kwargs):
        nonlocal called
        called = True
        return _download()

    result = run_world_bank_operational_once(
        session,
        build_world_bank_operational_monitor(enabled=True),
        SAFE,
        now=NOW,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        allow_network=True,
        allow_write=True,
        download=download,
        capacity_after=lambda: SAFE,
    )

    assert result.performed is False
    assert result.reason == "monitor_not_due"
    assert called is False


def test_world_bank_operational_monitor_records_indexed_success() -> None:
    calls = []
    result = _run(status="indexed", record_calls=calls)

    assert result.outcome is MonitorRunOutcome.SUCCESS
    assert result.status == "indexed"
    assert result.claim_count == 0
    assert result.chunk_count == 3
    assert result.observation_periods == ("2025", "2024", "2023")
    assert len(calls) == 1
    kwargs = calls[0][1]
    assert kwargs["outcome"] is MonitorRunOutcome.SUCCESS
    assert kwargs["discovered_count"] == 1
    assert kwargs["ingested_count"] == 1
    assert kwargs["duplicate_count"] == 0
    assert kwargs["last_document_sha256"] == "a" * 64


def test_world_bank_operational_monitor_records_exact_byte_duplicate_as_no_change() -> None:
    calls = []
    result = _run(status="already_indexed", record_calls=calls)

    assert result.outcome is MonitorRunOutcome.NO_CHANGE
    assert result.status == "already_indexed"
    kwargs = calls[0][1]
    assert kwargs["outcome"] is MonitorRunOutcome.NO_CHANGE
    assert kwargs["ingested_count"] == 0
    assert kwargs["duplicate_count"] == 1


def test_world_bank_operational_monitor_fails_closed_if_capacity_becomes_unsafe() -> None:
    calls = []
    unsafe = CapacityDecision(
        allow_ingestion=False,
        reason="capacity_low",
        blocking_services=("qdrant",),
    )
    result = _run(status="indexed", after=unsafe, record_calls=calls)

    assert result.outcome is MonitorRunOutcome.FAILED
    assert result.reason == "post_write_capacity_unsafe"
    assert result.blocking_services == ("qdrant",)
    kwargs = calls[0][1]
    assert kwargs["outcome"] is MonitorRunOutcome.FAILED
    assert kwargs["error_code"] == "capacity_blocked_after_write"
    assert kwargs["ingested_count"] == 1
