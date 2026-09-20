from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.monitoring.registry import MONITORS
from app.sources.registry import get_source


@dataclass(frozen=True, slots=True)
class ExpansionCandidate:
    candidate_id: str
    source_id: str
    api_url: str
    documentation_url: str
    api_standard: str
    adapter_implemented: bool = False
    bounded_query_contract_validated: bool = False
    temporal_policy_validated: bool = False
    persistence_path_implemented: bool = False
    offline_exact_byte_contract_validated: bool = False
    live_canary_runner_implemented: bool = False
    exact_byte_reconciliation_validated: bool = False
    bounded_live_canary_passed: bool = False


INTERNATIONAL_EXPANSION_CANDIDATES: tuple[ExpansionCandidate, ...] = (
    ExpansionCandidate(
        candidate_id="world-bank-indicators-v2",
        source_id="world_bank",
        api_url="https://api.worldbank.org/v2/",
        documentation_url="https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
        api_standard="World Bank Indicators API v2",
        adapter_implemented=True,
        bounded_query_contract_validated=True,
        temporal_policy_validated=True,
        persistence_path_implemented=True,
        offline_exact_byte_contract_validated=True,
        live_canary_runner_implemented=True,
        exact_byte_reconciliation_validated=True,
        bounded_live_canary_passed=True,
    ),
    ExpansionCandidate(
        candidate_id="imf-sdmx-v2",
        source_id="imf",
        api_url="https://sdmxcentral.imf.org/sdmx/v2/",
        documentation_url="https://data.imf.org/en/Resource-Pages/IMF-API",
        api_standard="SDMX 2.1/3.0",
        adapter_implemented=True,
        bounded_query_contract_validated=False,
        temporal_policy_validated=True,
        persistence_path_implemented=False,
        offline_exact_byte_contract_validated=True,
        live_canary_runner_implemented=False,
        exact_byte_reconciliation_validated=False,
        bounded_live_canary_passed=False,
    ),
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _candidate_snapshot(candidate: ExpansionCandidate) -> dict[str, object]:
    source = get_source(candidate.source_id)
    candidate_host = _host(candidate.api_url)
    host_allowlisted = candidate_host in source.allowed_hosts
    active_monitor_ids = [
        monitor.monitor_id
        for monitor in MONITORS
        if monitor.source_id == candidate.source_id and monitor.enabled
    ]

    checks = {
        "trusted_source_registered": True,
        "candidate_uses_https": candidate.api_url.startswith("https://"),
        "candidate_host_allowlisted": host_allowlisted,
        "source_specific_adapter_implemented": candidate.adapter_implemented,
        "bounded_query_contract_validated": candidate.bounded_query_contract_validated,
        "explicit_temporal_policy_validated": candidate.temporal_policy_validated,
        "persistence_path_implemented": candidate.persistence_path_implemented,
        "offline_exact_byte_contract_validated": candidate.offline_exact_byte_contract_validated,
        "live_canary_runner_implemented": candidate.live_canary_runner_implemented,
        "exact_byte_reconciliation_validated": candidate.exact_byte_reconciliation_validated,
        "bounded_live_canary_passed": candidate.bounded_live_canary_passed,
        "already_in_live_monitor_registry": bool(active_monitor_ids),
    }

    activation_blockers = [
        name
        for name, passed in checks.items()
        if name != "already_in_live_monitor_registry" and not passed
    ]
    production_activated = bool(active_monitor_ids) and not activation_blockers
    activation_ready = not active_monitor_ids and not activation_blockers

    return {
        "candidate_id": candidate.candidate_id,
        "source_id": source.source_id,
        "source_name": source.name,
        "authority_level": source.authority_level.value,
        "independence_group": source.independence_group or source.source_id,
        "api_url": candidate.api_url,
        "api_host": candidate_host,
        "documentation_url": candidate.documentation_url,
        "api_standard": candidate.api_standard,
        "checks": checks,
        "active_monitor_ids": active_monitor_ids,
        "activation_blockers": activation_blockers,
        "activation_ready": activation_ready,
        "production_activated": production_activated,
    }


def build_international_expansion_readiness() -> dict[str, object]:
    """Return a secret-free, non-operational source-expansion readiness report."""
    candidates = [_candidate_snapshot(item) for item in INTERNATIONAL_EXPANSION_CANDIDATES]
    activated_count = sum(1 for row in candidates if row["production_activated"])
    return {
        "mode": "read_only_source_expansion_readiness",
        "candidates": candidates,
        "summary": {
            "candidate_count": len(candidates),
            "activation_ready": sum(1 for row in candidates if row["activation_ready"]),
            "production_activated": activated_count,
            "blocked": sum(
                1
                for row in candidates
                if not row["activation_ready"] and not row["production_activated"]
            ),
            "live_monitor_additions": activated_count,
        },
        "rollout_gate": {
            "current_live_source_set_unchanged": False,
            "requires_initial_scheduler_rollout_closeout_before_activation": True,
            "initial_scheduler_rollout_closed": True,
            "activation_performed_by_this_milestone": True,
        },
        "safety": {
            "read_only": True,
            "performs_network_fetch": False,
            "widens_allowlist": False,
            "creates_monitor": False,
            "changes_scheduler": False,
            "changes_ingestion": False,
            "mutates_evidence": False,
            "note": (
                "World Bank remains production-active under its bounded contract. The IMF CPI offline adapter "
                "and temporal contract are implemented, but IMF remains blocked pending exact live query/auth "
                "validation, source-policy review, persistence/reconciliation, and a bounded live canary."
            ),
        },
    }
