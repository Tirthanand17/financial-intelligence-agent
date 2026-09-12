from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest

import app.services.ingestion as ingestion_service
from app.ingestion.downloader import DownloadedDocument
from app.sources.registry import get_source


def _downloaded(content: bytes) -> DownloadedDocument:
    source = get_source("rbi")
    url = "https://www.rbi.org.in/press-release/123"
    return DownloadedDocument(
        source=source,
        source_url=url,
        final_url=url,
        content=content,
        content_type="text/plain",
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )


def test_expected_sha_mismatch_fails_before_any_persistence(monkeypatch) -> None:
    downloaded = _downloaded(b"changed after preflight")
    persistence_touched = False

    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(
            trust_promotion_enabled=False,
            chunk_size_chars=3500,
            chunk_overlap_chars=400,
        ),
    )
    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: downloaded,
    )

    def fail_if_persistence_starts():
        nonlocal persistence_touched
        persistence_touched = True
        raise AssertionError("persistence must not start after a SHA mismatch")

    monkeypatch.setattr(ingestion_service, "get_session", fail_if_persistence_starts)

    with pytest.raises(ValueError, match="changed after preflight"):
        ingestion_service.ingest_url(
            "rbi",
            downloaded.source_url,
            expected_sha256="0" * 64,
        )

    assert persistence_touched is False


def test_expected_sha_exact_match_reaches_normal_ingestion_boundary(monkeypatch) -> None:
    downloaded = _downloaded(b"stable preflight bytes")
    persistence_touched = False

    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(
            trust_promotion_enabled=False,
            chunk_size_chars=3500,
            chunk_overlap_chars=400,
        ),
    )
    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: downloaded,
    )

    def boundary_probe():
        nonlocal persistence_touched
        persistence_touched = True
        raise RuntimeError("normal persistence boundary reached")

    monkeypatch.setattr(ingestion_service, "get_session", boundary_probe)

    with pytest.raises(RuntimeError, match="normal persistence boundary reached"):
        ingestion_service.ingest_url(
            "rbi",
            downloaded.source_url,
            expected_sha256=downloaded.sha256,
        )

    assert persistence_touched is True
