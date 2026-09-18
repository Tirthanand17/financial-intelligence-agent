from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.services.world_bank_persistence as persistence
import app.storage.object_store as object_store
from app.sources.world_bank import build_world_bank_indicator_url
from app.storage.database import Base, ClaimRecord, DocumentRecord


def _payload() -> bytes:
    return json.dumps(
        [
            {
                "page": 1,
                "pages": 1,
                "per_page": 2,
                "total": 2,
                "lastupdated": "2026-09-17",
            },
            [
                {
                    "indicator": {
                        "id": "NY.GDP.MKTP.KD.ZG",
                        "value": "GDP growth (annual %)",
                    },
                    "country": {"id": "IN", "value": "India"},
                    "countryiso3code": "IND",
                    "date": "2025",
                    "value": 6.5,
                    "unit": "",
                    "obs_status": "",
                    "decimal": 1,
                },
                {
                    "indicator": {
                        "id": "NY.GDP.MKTP.KD.ZG",
                        "value": "GDP growth (annual %)",
                    },
                    "country": {"id": "IN", "value": "India"},
                    "countryiso3code": "IND",
                    "date": "2024",
                    "value": 6.1,
                    "unit": "",
                    "obs_status": "",
                    "decimal": 1,
                },
            ],
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _install_fake_stores(monkeypatch, Session, *, corrupt_raw: bool = False, qdrant_ok: bool = True):
    raw_store: dict[str, bytes] = {}
    indexed: dict[str, list[str]] = {}
    index_calls: list[str] = []

    monkeypatch.setattr(persistence, "get_session", lambda: Session())

    def fake_put_raw_document(*, source_id: str, sha256: str, content: bytes, content_type: str) -> str:
        assert source_id == "world_bank"
        assert content_type == "application/json"
        key = f"raw/{source_id}/{sha256}.json"
        raw_store[key] = b"corrupted" if corrupt_raw else content
        return key

    monkeypatch.setattr(persistence, "put_raw_document", fake_put_raw_document)
    monkeypatch.setattr(persistence, "get_raw_document", lambda key: raw_store[key])

    def fake_index_chunks(*, document_id: str, chunks: list[str], payload_base: dict[str, object]) -> None:
        assert payload_base["source_id"] == "world_bank"
        assert payload_base["temporal_semantics"] == "annual_observation_period_not_claim_date"
        indexed[document_id] = list(chunks)
        index_calls.append(document_id)

    def fake_count(*, document_id: str, chunk_count: int) -> int:
        if not qdrant_ok:
            return 0
        return len(indexed.get(document_id, []))

    monkeypatch.setattr(persistence, "index_chunks", fake_index_chunks)
    monkeypatch.setattr(persistence, "count_indexed_document_points", fake_count)
    return raw_store, indexed, index_calls


def test_world_bank_payload_is_preserved_reconciled_and_idempotent(monkeypatch) -> None:
    Session = _session_factory()
    raw_store, indexed, index_calls = _install_fake_stores(monkeypatch, Session)
    content = _payload()
    digest = sha256(content).hexdigest()
    url = build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=2)

    first = persistence.persist_world_bank_payload(
        content=content,
        indicator_code="NY.GDP.MKTP.KD.ZG",
        source_url=url,
        final_url=url,
        recent_observations=2,
        retrieved_at=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
        expected_sha256=digest,
    )

    assert first.status == "indexed"
    assert first.sha256 == digest
    assert first.object_key.endswith(".json")
    assert first.chunk_count == 2
    assert first.claim_count == 0
    assert first.source_last_updated == "2026-09-17"
    assert first.observation_periods == ("2025", "2024")
    assert first.live_canary_performed is False
    assert raw_store[first.object_key] == content
    assert len(indexed[first.document_id]) == 2
    assert "Observation period: 2025 (annual observation period; not a publication/effective date)" in indexed[first.document_id][0]
    assert "Claim publication date: unknown" in indexed[first.document_id][0]
    assert "Claim effective date: unknown" in indexed[first.document_id][0]

    second = persistence.persist_world_bank_payload(
        content=content,
        indicator_code="NY.GDP.MKTP.KD.ZG",
        source_url=url,
        final_url=url,
        recent_observations=2,
        retrieved_at=datetime(2026, 9, 18, 5, 1, tzinfo=UTC),
        expected_sha256=digest,
    )
    assert second.status == "already_indexed"
    assert second.document_id == first.document_id
    assert index_calls == [first.document_id]

    with Session() as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ClaimRecord)) == 0
        row = session.scalar(select(DocumentRecord))
        assert row is not None
        assert row.status == "indexed"
        assert row.content_type == "application/json"
        assert row.source_id == "world_bank"
        assert row.chunk_count == 2


def test_expected_hash_mismatch_fails_before_any_persistence(monkeypatch) -> None:
    Session = _session_factory()
    raw_store, _, index_calls = _install_fake_stores(monkeypatch, Session)
    url = build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=2)

    with pytest.raises(ValueError, match="expected SHA-256"):
        persistence.persist_world_bank_payload(
            content=_payload(),
            indicator_code="NY.GDP.MKTP.KD.ZG",
            source_url=url,
            final_url=url,
            recent_observations=2,
            retrieved_at=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
            expected_sha256="0" * 64,
        )

    assert raw_store == {}
    assert index_calls == []
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_raw_replay_hash_mismatch_preserves_evidence_and_blocks_database_commit(monkeypatch) -> None:
    Session = _session_factory()
    raw_store, _, index_calls = _install_fake_stores(
        monkeypatch,
        Session,
        corrupt_raw=True,
    )
    content = _payload()
    url = build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=2)

    with pytest.raises(RuntimeError, match="RAW_EVIDENCE_HASH_MISMATCH"):
        persistence.persist_world_bank_payload(
            content=content,
            indicator_code="NY.GDP.MKTP.KD.ZG",
            source_url=url,
            final_url=url,
            recent_observations=2,
            retrieved_at=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
        )

    assert len(raw_store) == 1
    assert index_calls == []
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_qdrant_mismatch_leaves_reconciliation_required_record(monkeypatch) -> None:
    Session = _session_factory()
    raw_store, _, index_calls = _install_fake_stores(
        monkeypatch,
        Session,
        qdrant_ok=False,
    )
    content = _payload()
    url = build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=2)

    with pytest.raises(RuntimeError, match="QDRANT_RECONCILIATION_MISMATCH"):
        persistence.persist_world_bank_payload(
            content=content,
            indicator_code="NY.GDP.MKTP.KD.ZG",
            source_url=url,
            final_url=url,
            recent_observations=2,
            retrieved_at=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
        )

    assert len(raw_store) == 1
    assert len(index_calls) == 1
    with Session() as session:
        row = session.scalar(select(DocumentRecord))
        assert row is not None
        assert row.status == "reconciliation_required"
        assert session.scalar(select(func.count()).select_from(ClaimRecord)) == 0


def test_candidate_url_scope_and_retrieval_timestamp_fail_closed_before_writes(monkeypatch) -> None:
    Session = _session_factory()
    raw_store, _, index_calls = _install_fake_stores(monkeypatch, Session)
    url = build_world_bank_indicator_url("NY.GDP.MKTP.KD.ZG", recent_observations=2)

    with pytest.raises(ValueError, match="query"):
        persistence.persist_world_bank_payload(
            content=_payload(),
            indicator_code="NY.GDP.MKTP.KD.ZG",
            source_url=url + "&date=1960:2025",
            final_url=url,
            recent_observations=2,
            retrieved_at=datetime(2026, 9, 18, 5, 0, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        persistence.persist_world_bank_payload(
            content=_payload(),
            indicator_code="NY.GDP.MKTP.KD.ZG",
            source_url=url,
            final_url=url,
            recent_observations=2,
            retrieved_at=datetime(2026, 9, 18, 5, 0),
        )

    assert raw_store == {}
    assert index_calls == []


def test_object_store_uses_json_extension_for_json_evidence(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def head_bucket(self, **kwargs):
            calls.append({"head": kwargs})

        def put_object(self, **kwargs):
            calls.append({"put": kwargs})

    settings = type("Settings", (), {"s3_bucket": "evidence"})()
    monkeypatch.setattr(object_store, "get_settings", lambda: settings)
    monkeypatch.setattr(object_store, "get_s3_client", lambda: FakeClient())

    key = object_store.put_raw_document(
        source_id="world_bank",
        sha256="a" * 64,
        content=b"{}",
        content_type="application/json; charset=utf-8",
    )

    assert key == f"raw/world_bank/{'a' * 64}.json"
    put_call = next(item["put"] for item in calls if "put" in item)
    assert put_call["Body"] == b"{}"
    assert put_call["ContentType"] == "application/json; charset=utf-8"
