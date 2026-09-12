from dataclasses import dataclass
from io import BytesIO

import pymupdf
from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    title: str | None
    text: str


def extract_document(content: bytes, content_type: str) -> ExtractedDocument:
    if content_type == "application/pdf":
        return _extract_pdf(content)
    if content_type == "text/html":
        return _extract_html(content)
    if content_type == "text/plain":
        text = content.decode("utf-8", errors="replace").strip()
        return ExtractedDocument(title=None, text=text)
    raise ValueError(f"Unsupported extraction content type: {content_type}")


def _extract_pdf(content: bytes) -> ExtractedDocument:
    document = pymupdf.open(stream=BytesIO(content), filetype="pdf")
    metadata = document.metadata or {}
    title = (metadata.get("title") or "").strip() or None
    pages: list[str] = []
    for page in document:
        text = page.get_text("text").strip()
        if text:
            pages.append(text)
    combined = "\n\n".join(pages).strip()
    if not combined:
        raise ValueError("No extractable text found in PDF")
    return ExtractedDocument(title=title, text=combined)


def _extract_html(content: bytes) -> ExtractedDocument:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    text = "\n".join(
        line.strip()
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    )
    if not text:
        raise ValueError("No extractable text found in HTML")
    return ExtractedDocument(title=title, text=text)
