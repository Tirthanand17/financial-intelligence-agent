from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.sources.expansion_readiness as expansion
from app.main import app
from app.monitoring.registry import MONITORS


client = TestClient(app)


def test_world_bank_is_activated_and_imf_remains_blocked() -> None:
    result = expansion.build_international_expansion_readiness()

    assert result["summary"] == {
        "candidate_count": 2,
        "activation_ready": 0,
        "production_activated": 1,
        "blocked": 1,
        "live_monitor_additions": 1,
    }
    assert result["rollout_gate"]["current_live_source_set_unchanged"] is False
    assert result["rollout_gate"]["requires_initial_scheduler_rollout_closeout_before_activation"] is True
    assert result["rollout_gate"]["initial_scheduler_rollout_closed"] is True
    assert result["rollout_gate"]["activation_performed_by_this_milestone"] is True

    by_source = {row["source_id"]: row for row in result["candidates"]}
    assert set(by_source) == {"world_bank", "imf"}

    world_bank = by_source["world_bank"]
    assert world_bank["candidate_id"] == "world-bank-indicators-v2"
    assert world_bank["checks"]["trusted_source_registered"] is True
    assert world_bank["checks"]["candidate_uses_https"] is True
    assert world_bank["checks"]["candidate_host_allowlisted"] is True
    assert world_bank["checks"]["source_specific_adapter_implemented"] is True
    assert world_bank["checks"]["bounded_query_contract_validated"] is True
    assert world_bank["checks"]["explicit_temporal_policy_validated"] is True
    assert world_bank["checks"]["persistence_path_implemented"] is True
    assert world_bank["checks"]["offline_exact_byte_contract_validated"] is True
    assert world_bank["checks"]["live_canary_runner_implemented"] is True
    assert world_bank["checks"]["exact_byte_reconciliation_validated"] is True
    assert world_bank["checks"]["bounded_live_canary_passed"] is True
    assert world_bank["checks"]["already_in_live_monitor_registry"] is True
    assert world_bank["active_monitor_ids"] == ["world-bank-india-gdp-api"]
    assert world_bank["activation_blockers"] == []
    assert world_bank["activation_ready"] is False
    assert world_bank["production_activated"] is True

    imf = by_source["imf"]
    assert imf["candidate_id"] == "imf-sdmx-v2"
    assert imf["checks"]["trusted_source_registered"] is True
    assert imf["checks"]["candidate_uses_https"] is True
    assert imf["checks"]["candidate_host_allowlisted"] is False
    assert imf["checks"]["source_specific_adapter_implemented"] is False
    assert imf["checks"]["bounded_query_contract_validated"] is False
    assert imf["checks"]["explicit_temporal_policy_validated"] is False
    assert imf["checks"]["persistence_path_implemented"] is False
    assert imf["checks"]["offline_exact_byte_contract_validated"] is False
    assert imf["checks"]["live_canary_runner_implemented"] is False
    assert "candidate_host_allowlisted" in imf["activation_blockers"]
    assert "live_canary_runner_implemented" in imf["activation_blockers"]
    assert imf["activation_ready"] is False
    assert imf["production_activated"] is False

    live_source_ids = {monitor.source_id for monitor in MONITORS if monitor.enabled}
    assert live_source_ids == {"rbi", "sebi", "nse", "mospi", "world_bank"}
    assert "imf" not in live_source_ids

    assert result["safety"]["performs_network_fetch"] is False
    assert result["safety"]["widens_allowlist"] is False
    assert result["safety"]["creates_monitor"] is False
    assert result["safety"]["changes_scheduler"] is False
    assert result["safety"]["changes_ingestion"] is False
    assert result["safety"]["mutates_evidence"] is False


def test_source_expansion_routes_reuse_dashboard_auth_and_are_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )

    assert client.get("/dashboard/source-expansion").status_code == 401
    page = client.get("/dashboard/source-expansion", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/source-expansion/status",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "International Source Expansion Readiness" in page.text
    assert "World Bank" in page.text or "loading" in page.text.lower()
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()

    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    payload = status.json()
    assert payload["summary"]["activation_ready"] == 0
    assert payload["summary"]["production_activated"] == 1
    assert payload["summary"]["live_monitor_additions"] == 1
    assert payload["rollout_gate"]["activation_performed_by_this_milestone"] is True
