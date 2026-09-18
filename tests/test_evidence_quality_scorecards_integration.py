from app.api.dashboard_hub import DASHBOARD_HUB_HTML
from scripts.production_smoke import PROTECTED_PATHS


def test_quality_scorecards_are_linked_from_workspace() -> None:
    assert 'href="/dashboard/quality-scorecards"' in DASHBOARD_HUB_HTML
    assert "Evidence Quality Scorecards" in DASHBOARD_HUB_HTML


def test_quality_scorecards_are_in_production_smoke_contract() -> None:
    assert "/dashboard/quality-scorecards" in PROTECTED_PATHS
