from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest

import app.services.world_bank_live_canary as canary
from app.services.world_bank_persistence import WorldBankPersistenceResult


INDICATOR = "NY.GDP.MKTP.KD.ZG"


def _download() -> canary.WorldBankLiveDownload:
    content = b'[{"lastupdated":"2026-09-19"},[]]'
    url = (
        "https://api.worldbank.org/v2/country/IND/indicator/NY.GDP.MKTP.KD.ZG"
        "?format=json&mrv=3&per_page=3"
    )
    return canary.WorldBankLiveDownload(
        source_url=url,
        final_url=url,
        content=content,
        content_type="application/json",
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime(2026, 9, 20, 3, 0, tzinfo=UTC),
    )


def _persisted(*, claim_count: int = 0) -> WorldBankPersistenceResult:
    return WorldBankPersistenceResult(
        document_id="doc-world-bank",
        status="indexed",
        sha256=_download().sha256,
        object_key=f"raw/world_bank/{_download().sha256}.json",
        chunk_count=3,
        claim_count=claim_count,
        source_last_updated="2026-09-19",
        observation_periods=("2025", "2024", "2023"),
    )


def test_live_canary_requires_explicit_network_write_and_confirmation(monkeypatch) -> None:
    called = {"download": 0}
    monkeypatch.setattr(
        canary,
        "download_world_bank_live_payload",
        lambda *args, **kwargs: called.__setitem__("download", called["download"] + 1),
    )

    with pytest.raises(RuntimeError, match="EXPLICIT_NETWORK_AND_WRITE"):
        canary.run_world_bank_live_canary(indicator_code=INDICATOR)

    with pytest.raises(RuntimeError, match="CONFIRMATION_REQUIRED"):
        canary.run_world_bank_live_canary(
            indicator_code=INDICATOR,
            allow_network=True,
            allow_write=True,
        )

    assert called["download"] == 0


def test_live_canary_blocks_if_trust_or_operational_gates_are_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        canary,
        "get_settings",
        lambda: SimpleNamespace(
            trust_promotion_enabled=True,
            source_monitoring_enabled=False,
            source_auto_ingest_enabled=False,
        ),
    )
    with pytest.raises(RuntimeError, match="TRUST_PROMOTION_ENABLED"):
        canary._require_safe_runtime()

    monkeypatch.setattr(
        canary,
        "get_settings",
        lambda: SimpleNamespace(
            trust_promotion_enabled=False,
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=False,
        ),
    )
    with pytest.raises(RuntimeError, match="OPERATIONAL_GATES_ENABLED"):
        canary._require_safe_runtime()


def test_live_canary_persists_same_downloaded_bytes_and_checks_capacity_twice(monkeypatch) -> None:
    download = _download()
    capacity_calls = {"count": 0}
    captured = {}

    monkeypatch.setattr(canary, "_require_safe_runtime", lambda: None)
    monkeypatch.setattr(
        canary,
        "_require_capacity",
        lambda: capacity_calls.__setitem__("count", capacity_calls["count"] + 1),
    )
    monkeypatch.setattr(canary, "download_world_bank_live_payload", lambda *args, **kwargs: download)

    def fake_persist(**kwargs):
        captured.update(kwargs)
        return _persisted()

    monkeypatch.setattr(canary, "persist_world_bank_payload", fake_persist)

    result = canary.run_world_bank_live_canary(
        indicator_code=INDICATOR,
        recent_observations=3,
        allow_network=True,
        allow_write=True,
        confirmation=canary.WORLD_BANK_LIVE_CANARY_CONFIRMATION,
    )

    assert capacity_calls["count"] == 2
    assert captured["content"] is download.content
    assert captured["expected_sha256"] == download.sha256
    assert captured["source_url"] == download.source_url
    assert captured["final_url"] == download.final_url
    assert result.live_canary_performed is True
    assert result.claim_count == 0
    assert result.sha256 == download.sha256


def test_live_canary_rejects_any_unexpected_claim_creation(monkeypatch) -> None:
    monkeypatch.setattr(canary, "_require_safe_runtime", lambda: None)
    monkeypatch.setattr(canary, "_require_capacity", lambda: None)
    monkeypatch.setattr(canary, "download_world_bank_live_payload", lambda *args, **kwargs: _download())
    monkeypatch.setattr(canary, "persist_world_bank_payload", lambda **kwargs: _persisted(claim_count=1))

    with pytest.raises(RuntimeError, match="UNEXPECTED_CLAIM_CREATION"):
        canary.run_world_bank_live_canary(
            indicator_code=INDICATOR,
            allow_network=True,
            allow_write=True,
            confirmation=canary.WORLD_BANK_LIVE_CANARY_CONFIRMATION,
        )
