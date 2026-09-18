from app.api.dashboard_hub import DASHBOARD_HUB_HTML
from scripts.production_smoke import PROTECTED_PATHS


def test_provenance_graph_is_linked_from_workspace() -> None:
    assert 'href="/dashboard/provenance"' in DASHBOARD_HUB_HTML
    assert "Provenance Graph" in DASHBOARD_HUB_HTML


def test_provenance_graph_is_in_production_smoke_contract() -> None:
    assert "/dashboard/provenance" in PROTECTED_PATHS
