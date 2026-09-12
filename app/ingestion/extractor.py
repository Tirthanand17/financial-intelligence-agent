from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from io import BytesIO
import xml.etree.ElementTree as ET

import pymupdf
from bs4 import BeautifulSoup


_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


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
    if content_type in _XML_CONTENT_TYPES:
        return _extract_xml_feed(content)
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local_name(child.tag) in wanted:
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return None


def _plain_fragment(value: str | None) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text or None


def _publication_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.date()


def _extract_xml_feed(content: bytes) -> ExtractedDocument:
    """Extract RSS/Atom evidence without following embedded links.

    Official feeds are intended for automated syndication, so they provide a
    legitimate machine-readable discovery/evidence path when normal web pages are
    temporarily protected by browser challenges. The extractor never follows an
    item link or bypasses a challenge page. It preserves each item's own date and
    text locally so claim temporal attribution remains item-scoped rather than
    applying one date to the entire feed.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("Invalid XML/RSS document") from exc

    channel = next(
        (element for element in root.iter() if _local_name(element.tag) == "channel"),
        None,
    )
    feed_title = None
    if channel is not None:
        feed_title = _child_text(channel, "title")
    if feed_title is None:
        feed_title = _child_text(root, "title")

    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]

    blocks: list[str] = []
    for entry in entries:
        title = _plain_fragment(_child_text(entry, "title"))
        description = _plain_fragment(
            _child_text(entry, "description", "summary", "content")
        )
        date_value = _child_text(entry, "pubDate", "published", "updated")
        published = _publication_date(date_value)
        link = _child_text(entry, "link")
        if link is None:
            for child in entry:
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"].strip()
                    break

        lines: list[str] = []
        if title:
            lines.append(title)
        if published is not None:
            # This label is intentionally compatible with the conservative local
            # temporal parser and does not use a colon, avoiding false key/value
            # claim extraction from the date itself.
            lines.append(f"Published on {published.strftime('%d %B %Y')}")
        if description:
            lines.append(description)
        if link:
            lines.append(f"Item Link {link}")

        if lines:
            blocks.append("\n".join(lines))

    combined = "\n\n".join(blocks).strip()
    if not combined:
        raise ValueError("No extractable feed items found in XML/RSS document")

    return ExtractedDocument(title=feed_title, text=combined)
