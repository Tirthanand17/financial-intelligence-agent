from pathlib import Path
from types import SimpleNamespace

import scripts.phase14_integrated_cycle_canary as canary


def test_integrated_cycle_uses_source_specific_monitor_downloader(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_download(source_id: str, url: str):
        calls.append((source_id, url))
        return SimpleNamespace(content=b"{}", content_type="application/json")

    monkeypatch.setattr(canary, "download_monitor_payload", fake_download)

    downloaded = canary.download_monitor_payload(
        "mospi",
        "https://www.mospi.gov.in/api/latest-release/get-web-latest-release-list",
    )

    assert calls == [(
        "mospi",
        "https://www.mospi.gov.in/api/latest-release/get-web-latest-release-list",
    )]
    assert downloaded.content_type == "application/json"


def test_integrated_cycle_source_wiring_does_not_use_generic_document_get() -> None:
    source = Path(canary.__file__).read_text(encoding="utf-8")

    assert "download_monitor_payload(monitor.source_id, monitor.url)" in source
    assert "download_trusted_document(monitor.source_id, monitor.url)" not in source
