from hashlib import sha256
from types import SimpleNamespace

from app.recovery.readiness import verify_preserved_evidence


def _document(document_id: str, object_key: str, content: bytes):
    return SimpleNamespace(
        id=document_id,
        object_key=object_key,
        sha256=sha256(content).hexdigest(),
    )


def test_verify_preserved_evidence_passes_for_exact_bytes() -> None:
    content = b"authoritative evidence bytes"
    document = _document("doc-1", "raw/rbi/a.pdf", content)

    result = verify_preserved_evidence([document], loader=lambda _key: content)

    assert result["safe"] is True
    assert result["verified"] == 1
    assert result["hash_mismatch_document_ids"] == []
    assert result["missing_or_unreadable_document_ids"] == []


def test_verify_preserved_evidence_fails_on_hash_mismatch() -> None:
    document = _document("doc-2", "raw/sebi/a.pdf", b"expected")

    result = verify_preserved_evidence([document], loader=lambda _key: b"different")

    assert result["safe"] is False
    assert result["hash_mismatch_document_ids"] == ["doc-2"]
    assert result["verified"] == 0


def test_verify_preserved_evidence_fails_without_leaking_provider_error() -> None:
    document = _document("doc-3", "raw/nse/a.pdf", b"expected")

    def unavailable(_key: str) -> bytes:
        raise RuntimeError("secret-provider-detail")

    result = verify_preserved_evidence([document], loader=unavailable)

    assert result["safe"] is False
    assert result["missing_or_unreadable_document_ids"] == ["doc-3"]
    assert "secret-provider-detail" not in str(result)
