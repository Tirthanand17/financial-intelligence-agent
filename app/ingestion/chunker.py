def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    # Preserve meaningful source line boundaries while normalizing repeated
    # whitespace inside each line. This gives the QA layer cleaner evidence
    # units for HTML tables, rate lists, headings, and PDF text.
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    normalized = "\n".join(lines)
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    length = len(normalized)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            space_boundary = normalized.rfind(" ", start, end)
            newline_boundary = normalized.rfind("\n", start, end)
            boundary = max(space_boundary, newline_boundary)
            if boundary > start + chunk_size // 2:
                end = boundary

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= length:
            break
        start = max(0, end - overlap)

    return chunks
