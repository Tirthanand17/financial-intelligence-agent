from __future__ import annotations

import csv
import hashlib
import io
import json

import httpx


DATA_URL = (
    "https://sdmxcentral.imf.org/sdmx/v2/data/dataflow/IMF/CPI/1.0/"
    "CPI.IN.PCPI_IX._Z.M"
)
MAX_BYTES = 256 * 1024
MAX_OBSERVATIONS = 3
EXPECTED = {
    "DATA_DOMAIN": "CPI",
    "REF_AREA": "IN",
    "INDICATOR": "PCPI_IX",
    "COUNTERPART_AREA": "_Z",
    "FREQ": "M",
}


def main() -> None:
    with httpx.Client(
        timeout=20.0,
        follow_redirects=False,
        headers={
            "Accept": "application/vnd.sdmx.data+csv;version=2.0",
            "User-Agent": "financial-intelligence-agent-imf-data-probe/1",
        },
    ) as client:
        response = client.get(DATA_URL, params={"lastNObservations": str(MAX_OBSERVATIONS)})

    if 300 <= response.status_code < 400:
        raise SystemExit(f"FINAL: BLOCKED - redirect rejected ({response.status_code})")
    if response.status_code != 200:
        raise SystemExit(f"FINAL: BLOCKED - unexpected IMF data status {response.status_code}")

    content_type = response.headers.get("content-type", "").lower()
    if "csv" not in content_type:
        raise SystemExit(f"FINAL: BLOCKED - unexpected IMF data content type {content_type}")

    content = response.content
    if not content or len(content) > MAX_BYTES:
        raise SystemExit(f"FINAL: BLOCKED - unsafe IMF data response size {len(content)}")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SystemExit("FINAL: BLOCKED - IMF SDMX-CSV is not UTF-8") from exc

    reader = csv.DictReader(io.StringIO(text))
    required = set(EXPECTED) | {"TIME_PERIOD", "OBS_VALUE"}
    fieldnames = set(reader.fieldnames or ())
    missing = sorted(required - fieldnames)
    if missing:
        raise SystemExit("FINAL: BLOCKED - missing IMF data columns: " + ",".join(missing))

    rows: list[dict[str, str]] = []
    for raw in reader:
        if not raw or not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
            continue
        row = {key: (value or "").strip() for key, value in raw.items() if key is not None}
        for key, expected in EXPECTED.items():
            if row.get(key) != expected:
                raise SystemExit(
                    f"FINAL: BLOCKED - IMF data key mismatch for {key}: {row.get(key)!r}"
                )
        rows.append(row)
        if len(rows) > MAX_OBSERVATIONS:
            raise SystemExit("FINAL: BLOCKED - IMF data exceeded three-observation bound")

    if not rows:
        raise SystemExit("FINAL: BLOCKED - IMF data query returned no observations")

    result = {
        "url": str(response.url),
        "status": response.status_code,
        "content_type": content_type,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "observation_count": len(rows),
        "periods": [row["TIME_PERIOD"] for row in rows],
        "statuses": [row.get("OBS_STATUS", "") for row in rows],
        "base_periods": [row.get("BASE_PER", "") for row in rows],
        "unit_multipliers": [row.get("UNIT_MULT", "") for row in rows],
        "values": [row["OBS_VALUE"] for row in rows],
        "key": EXPECTED,
    }
    print("RESULT_JSON: " + json.dumps(result, sort_keys=True))
    print(
        "FINAL: PASS-READ-ONLY - exact bounded IMF CPI monthly data query validated; "
        "no persistence or cloud writes performed."
    )


if __name__ == "__main__":
    main()
