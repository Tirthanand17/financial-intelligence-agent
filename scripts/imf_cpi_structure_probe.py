from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx


BASE = "https://sdmxcentral.imf.org/sdmx/v2/structure"
URLS = {
    "constraint": f"{BASE}/contentconstraint/IMF/CPI_CONSTRAINT/latest/",
    "data_domain": f"{BASE}/codelist/IMF/CL_DATADOMAIN/1.0/",
    "ref_area": f"{BASE}/codelist/IMF/CL_REF_AREA/1.0/",
    "indicator": f"{BASE}/codelist/IMF/CL_INDICATOR/1.0/",
    "frequency": f"{BASE}/codelist/SDMX/CL_FREQ/1.0/",
}
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
        raise RuntimeError(f"unexpected_status:{response.status_code}:{url}")
    content_type = response.headers.get("content-type", "").lower()
    if "xml" not in content_type:
        raise RuntimeError(f"unexpected_content_type:{content_type}")
    content = response.content
    if not content or len(content) > MAX_BYTES:
        raise RuntimeError(f"unsafe_response_size:{len(content)}:{url}")
    return ProbeResponse(str(response.url), content_type, content)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_name(element: ET.Element) -> str:
    for child in element:
        if _local(child.tag) == "Name" and (child.text or "").strip():
            return " ".join((child.text or "").split())
    return ""


def _codelist_matches(root: ET.Element, wanted_codes: set[str], wanted_names: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for element in root.iter():
        if _local(element.tag) != "Code":
            continue
        code = element.attrib.get("id", "")
        name = _text_name(element)
        if code in wanted_codes or name.strip().lower() in wanted_names:
            rows.append({"code": code, "name": name})
    return rows


def _constraint_values(root: ET.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for key_value in root.iter():
        if _local(key_value.tag) not in {"KeyValue", "CubeRegionKeyValue"}:
            continue
        dimension = key_value.attrib.get("id")
        if not dimension:
            continue
        found: list[str] = []
        for child in key_value.iter():
            if _local(child.tag) != "Value":
                continue
            value = child.attrib.get("value") or (child.text or "").strip()
            if value:
                found.append(value)
        if found:
            values.setdefault(dimension, [])
            values[dimension].extend(found)
    return {key: sorted(set(items)) for key, items in values.items()}


def _summary(label: str, response: ProbeResponse) -> dict[str, object]:
    return {
        "label": label,
        "url": response.url,
        "content_type": response.content_type,
        "bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }


def main() -> None:
    responses = {label: _fetch(url) for label, url in URLS.items()}
    roots = {label: ET.fromstring(response.content) for label, response in responses.items()}

    result = {
        "responses": [_summary(label, response) for label, response in responses.items()],
        "constraint_values": _constraint_values(roots["constraint"]),
        "matches": {
            "data_domain": _codelist_matches(
                roots["data_domain"],
                {"CPI"},
                {"consumer price index", "prices"},
            ),
            "ref_area": _codelist_matches(
                roots["ref_area"],
                {"IND", "IN"},
                {"india"},
            ),
            "indicator": _codelist_matches(
                roots["indicator"],
                {"PCPI_IX"},
                {"consumer price index, all items", "consumer price index, all items, index"},
            ),
            "frequency": _codelist_matches(
                roots["frequency"],
                {"A", "Q", "M"},
                {"annual", "quarterly", "monthly"},
            ),
        },
    }
    print("RESULT_JSON: " + json.dumps(result, sort_keys=True))

    constraint = result["constraint_values"]
    matches = result["matches"]
    if not matches["ref_area"]:
        raise SystemExit("FINAL: BLOCKED - India code not resolved from IMF CL_REF_AREA")
    if not any(row["code"] == "PCPI_IX" for row in matches["indicator"]):
        raise SystemExit("FINAL: BLOCKED - PCPI_IX not resolved from IMF CL_INDICATOR")
    if not constraint:
        raise SystemExit("FINAL: BLOCKED - CPI constraint returned no key values")
    print(
        "FINAL: PASS-READ-ONLY - IMF CPI constraint and key-code evidence resolved; "
        "no data or cloud writes performed."
    )


if __name__ == "__main__":
    main()
