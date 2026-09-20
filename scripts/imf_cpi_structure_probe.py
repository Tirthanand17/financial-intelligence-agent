from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx


BASE = "https://sdmxcentral.imf.org/sdmx/v2/structure"
DATAFLOW_URL = f"{BASE}/dataflow/IMF/CPI/1.0/"
DATASTRUCTURE_URL = f"{BASE}/datastructure/IMF/CPI/1.0/"
MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProbeResponse:
    url: str
    content_type: str
    content: bytes


def _fetch(url: str) -> ProbeResponse:
    with httpx.Client(
        timeout=20.0,
        follow_redirects=False,
        headers={
            "Accept": "application/vnd.sdmx.structure+xml;version=2.1",
            "User-Agent": "financial-intelligence-agent-imf-structure-probe/1",
        },
    ) as client:
        response = client.get(
            url,
            params={"references": "all", "partial": "true"},
        )
    if 300 <= response.status_code < 400:
        raise RuntimeError(f"redirect_rejected:{response.status_code}")
    if response.status_code != 200:
        raise RuntimeError(f"unexpected_status:{response.status_code}")
    content_type = response.headers.get("content-type", "").lower()
    if "xml" not in content_type:
        raise RuntimeError(f"unexpected_content_type:{content_type}")
    content = response.content
    if not content or len(content) > MAX_BYTES:
        raise RuntimeError(f"unsafe_response_size:{len(content)}")
    return ProbeResponse(str(response.url), content_type, content)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _name(element: ET.Element) -> str | None:
    for child in element:
        if _local(child.tag) == "Name" and (child.text or "").strip():
            return " ".join((child.text or "").split())
    return None


def _dimensions(root: ET.Element) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for element in root.iter():
        kind = _local(element.tag)
        if kind not in {"Dimension", "TimeDimension", "MeasureDimension"}:
            continue
        dim_id = element.attrib.get("id")
        if not dim_id:
            continue
        position_text = element.attrib.get("position")
        try:
            position = int(position_text) if position_text else None
        except ValueError:
            position = None
        enum_ref = None
        for node in element.iter():
            if _local(node.tag) in {"Ref", "URN"}:
                ref_id = node.attrib.get("id") or (node.text or "").strip() or None
                if ref_id:
                    enum_ref = ref_id
        rows.append(
            {
                "id": dim_id,
                "kind": kind,
                "position": position,
                "representation_ref": enum_ref,
            }
        )
    rows.sort(key=lambda item: (item["position"] is None, item["position"] or 10_000, str(item["id"])))
    return rows


def _india_codes(root: ET.Element) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    current_codelist = ""
    for element in root.iter():
        kind = _local(element.tag)
        if kind == "Codelist":
            current_codelist = element.attrib.get("id", "")
        if kind != "Code":
            continue
        code = element.attrib.get("id", "")
        label = _name(element) or ""
        if "india" in label.lower():
            matches.append({"codelist": current_codelist, "code": code, "name": label})
    return matches


def _indicator_codes(root: ET.Element) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    current_codelist = ""
    for element in root.iter():
        kind = _local(element.tag)
        if kind == "Codelist":
            current_codelist = element.attrib.get("id", "")
        if kind != "Code":
            continue
        code = element.attrib.get("id", "")
        if code != "PCPI_IX":
            continue
        matches.append(
            {
                "codelist": current_codelist,
                "code": code,
                "name": _name(element) or "",
            }
        )
    return matches


def _summarize(label: str, response: ProbeResponse) -> dict[str, object]:
    root = ET.fromstring(response.content)
    return {
        "label": label,
        "url": response.url,
        "content_type": response.content_type,
        "bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "dimensions": _dimensions(root),
        "india_codes": _india_codes(root),
        "pcpi_ix_codes": _indicator_codes(root),
    }


def main() -> None:
    results = [
        _summarize("dataflow", _fetch(DATAFLOW_URL)),
        _summarize("datastructure", _fetch(DATASTRUCTURE_URL)),
    ]
    print("RESULT_JSON: " + json.dumps(results, sort_keys=True))

    combined_india = [row for result in results for row in result["india_codes"]]
    combined_indicator = [row for result in results for row in result["pcpi_ix_codes"]]
    combined_dimensions = [row for result in results for row in result["dimensions"]]
    if not combined_dimensions:
        raise SystemExit("FINAL: BLOCKED - no CPI dimensions discovered")
    if not combined_india:
        raise SystemExit("FINAL: BLOCKED - India code not found in constrained CPI structure references")
    if not combined_indicator:
        raise SystemExit("FINAL: BLOCKED - PCPI_IX not found in constrained CPI structure references")
    print("FINAL: PASS-READ-ONLY - IMF CPI live structure contract discovered; no data or cloud writes performed.")


if __name__ == "__main__":
    main()
