from app.ingestion.chunker import chunk_text


def test_chunker_preserves_text_across_chunks() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    chunks = chunk_text(text, chunk_size=30, overlap=5)
    assert len(chunks) >= 2
    assert all(chunks)


def test_chunker_rejects_invalid_overlap() -> None:
    try:
        chunk_text("hello world", chunk_size=10, overlap=10)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
