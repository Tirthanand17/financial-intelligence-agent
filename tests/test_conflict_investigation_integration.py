from app.api.dashboard_hub import DASHBOARD_HUB_HTML
from scripts.production_smoke import PROTECTED_PATHS


def test_conflict_investigation_is_linked_from_workspace() -> None:
    assert 'href="/dashboard/conflicts"' in DASHBOARD_HUB_HTML
    assert "Conflict Investigation" in DASHBOARD_HUB_HTML


def test_conflict_investigation_is_in_production_smoke_contract() -> None:
    assert "/dashboard/conflicts" in PROTECTED_PATHS
