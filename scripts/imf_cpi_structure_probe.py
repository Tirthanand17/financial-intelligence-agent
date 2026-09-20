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
        response = client.get(url, params={"references": "none"})
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


def _reference(node: ET.Element) -> dict[str, str] | None:
    if _local(node.tag) != "Ref":
        return None
    values = {
        key: value
        for key in ("agencyID", "id", "version", "class", "package", "maintainableParentID")
        if (value := node.attrib.get(key))
    }
    return values or None


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
        references: list[dict[str, str]] = []
        for node in element.iter():
            ref = _reference(node)
            if ref is not None:
                references.append(ref)
        rows.append(
            {
                "id": dim_id,
                "kind": kind,
                "position": position,
                "references": references,
            }
        )
    rows.sort(key=lambda item: (item["position"] is None, item["position"] or 10_000, str(item["id"])))
    return rows


def _all_references(root: ET.Element) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for node in root.iter():
        ref = _reference(node)
        if ref is None:
            continue
        key = tuple(sorted(ref.items()))
        if key in seen:
            continue
        seen.add(key)
        rows.append(ref)
    return rows


def _summarize(label: str, response: ProbeResponse) -> dict[str, object]:
    root = ET.fromstring(response.content)
    return {
        "label": label,
        "url": response.url,
        "content_type": response.content_type,
        "bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "dimensions": _dimensions(root),
        "references": _all_references(root),
    }


def main() -> None:
    results = [
        _summarize("dataflow", _fetch(DATAFLOW_URL)),
        _summarize("datastructure", _fetch(DATASTRUCTURE_URL)),
    ]
    print("RESULT_JSON: " + json.dumps(results, sort_keys=True))

    dsd = next(result for result in results if result["label"] == "datastructure")
    if not dsd["dimensions"]:
        raise SystemExit("FINAL: BLOCKED - no CPI dimensions discovered")
    print(
        "FINAL: PASS-READ-ONLY - bounded IMF CPI dataflow/DSD structure contract discovered; "
        "no data or cloud writes performed."
    )


if __name__ == "__main__":
    main()
