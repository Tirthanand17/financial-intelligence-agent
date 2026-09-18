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
    temporal_policy_validated: bool = False
    exact_byte_reconciliation_validated: bool = False
    bounded_live_canary_passed: bool = False


# These candidates are documentation/readiness records only. They are intentionally
# NOT added to app.monitoring.registry.MONITORS while the initial four-source
# production rollout remains under observation.
INTERNATIONAL_EXPANSION_CANDIDATES: tuple[ExpansionCandidate, ...] = (
    ExpansionCandidate(
        candidate_id="world-bank-indicators-v2",
        source_id="world_bank",
        api_url="https://api.worldbank.org/v2/",
        documentation_url="https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
        api_standard="World Bank Indicators API v2",
    ),
    ExpansionCandidate(
        candidate_id="imf-sdmx-v2",
        source_id="imf",
        api_url="https://sdmxcentral.imf.org/sdmx/v2/",
        documentation_url="https://data.imf.org/en/Resource-Pages/IMF-API",
        api_standard="SDMX 2.1/3.0",
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
        "explicit_temporal_policy_validated": candidate.temporal_policy_validated,
        "exact_byte_reconciliation_validated": candidate.exact_byte_reconciliation_validated,
        "bounded_live_canary_passed": candidate.bounded_live_canary_passed,
        "already_in_live_monitor_registry": bool(active_monitor_ids),
    }

    activation_blockers = [
        name
        for name, passed in checks.items()
        if name != "already_in_live_monitor_registry" and not passed
    ]
    if active_monitor_ids:
        activation_blockers.append("unexpected_existing_live_monitor")

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
        "activation_ready": not activation_blockers,
    }


def build_international_expansion_readiness() -> dict[str, object]:
    """Return a secret-free, non-operational source-expansion readiness report.

    This report does not fetch candidate APIs, widen source allow-lists, create
    monitors, persist discoveries, or alter scheduler/source-coverage policy.
    """
    candidates = [_candidate_snapshot(item) for item in INTERNATIONAL_EXPANSION_CANDIDATES]
    return {
        "mode": "read_only_source_expansion_readiness",
        "candidates": candidates,
        "summary": {
            "candidate_count": len(candidates),
            "activation_ready": sum(1 for row in candidates if row["activation_ready"]),
            "blocked": sum(1 for row in candidates if not row["activation_ready"]),
            "live_monitor_additions": 0,
        },
        "rollout_gate": {
            "current_live_source_set_unchanged": True,
            "requires_initial_scheduler_rollout_closeout_before_activation": True,
            "activation_performed_by_this_milestone": False,
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
                "Candidate metadata documents the work still required before any international source is activated. "
                "The existing RBI/SEBI/NSE/MoSPI production source set remains unchanged."
            ),
        },
    }
