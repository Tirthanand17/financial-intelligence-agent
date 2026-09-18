from app.api.dashboard_hub import DASHBOARD_HUB_HTML
from scripts.production_smoke import PROTECTED_PATHS


def test_document_detail_is_linked_from_workspace() -> None:
    assert 'href="/dashboard/document"' in DASHBOARD_HUB_HTML
    assert "Document Evidence Detail" in DASHBOARD_HUB_HTML


def test_document_detail_entry_page_is_in_production_smoke_contract() -> None:
    assert "/dashboard/document" in PROTECTED_PATHS
