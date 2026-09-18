from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth

router = APIRouter()


DASHBOARD_HUB_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Financial Intelligence Workspace</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1100px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:24px}.card{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 10px #0000000d}.card h2{margin:0 0 8px;font-size:19px}.muted{color:#6b7280;font-size:13px;line-height:1.45}.go{display:inline-block;margin-top:14px;background:#111827;color:#fff;padding:9px 13px;border-radius:9px;text-decoration:none}.tag{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef2ff;font-size:11px;font-weight:700;margin-top:8px}.notice{background:#fff7ed;color:#9a3412;border-radius:12px;padding:12px 14px;margin-top:20px}@media(max-width:700px){.top{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Financial Intelligence Workspace</h1><p class="muted">Private read-only navigation hub. Operational controls, ingestion controls, trust promotion, and destructive actions are intentionally absent.</p></div><a class="go" href="/dashboard">Operational Dashboard</a></div>
<div class="grid">
  <div class="card"><h2>Operational Dashboard</h2><p class="muted">Live documents, claims, vector reconciliation, queue counts, capacity, source monitors, and recent monitor runs.</p><span class="tag">OPERATIONS</span><br><a class="go" href="/dashboard">Open</a></div>
  <div class="card"><h2>Operational Readiness</h2><p class="muted">Fail-closed safety summary for capacity, Qdrant parity, runtime gates, trust events, monitor readiness, and cloud measurements.</p><span class="tag">SAFETY</span><br><a class="go" href="/dashboard/readiness">Open</a></div>
  <div class="card"><h2>Capacity Headroom Planner</h2><p class="muted">Exact measured Supabase, B2, and Qdrant headroom against project safety ceilings and the reserved low-watermark pause threshold. No quota or exhaustion-date guessing.</p><span class="tag">CAPACITY</span><br><a class="go" href="/dashboard/capacity-plan">Open</a></div>
  <div class="card"><h2>Source Expansion Readiness</h2><p class="muted">Pre-activation checks for World Bank and IMF official API candidates. No allow-list widening, live monitor creation, canary, or scheduler change is performed here.</p><span class="tag">SOURCES</span><br><a class="go" href="/dashboard/source-expansion">Open</a></div>
  <div class="card"><h2>Incident Center</h2><p class="muted">Deterministic operator alerts for unsafe capacity, reconciliation mismatch, runtime-gate drift, monitor failures, queue failures, missing measurements, or unexpected trust events.</p><span class="tag">ALERTS</span><br><a class="go" href="/dashboard/incidents">Open</a></div>
  <div class="card"><h2>Intelligence Evidence</h2><p class="muted">Human-readable current structured evidence, source coverage, claim states, conflicts, and recent indexed documents.</p><span class="tag">INTELLIGENCE</span><br><a class="go" href="/dashboard/intelligence-view">Open</a></div>
  <div class="card"><h2>Intelligence Digest</h2><p class="muted">Deterministic daily/weekly-style digest of newly indexed evidence, factual changes, conflicts, and current operator incidents. No generated market narrative.</p><span class="tag">DIGEST</span><br><a class="go" href="/dashboard/digest">Open</a></div>
  <div class="card"><h2>Evidence Search</h2><p class="muted">Bounded search across persisted claim evidence and document provenance by text, source, entity, metric, state, and persisted temporal scope.</p><span class="tag">SEARCH</span><br><a class="go" href="/dashboard/search">Open</a></div>
  <div class="card"><h2>Evidence Export</h2><p class="muted">Download bounded JSON or CSV claim-evidence exports with source URLs, document SHA-256 provenance, persisted dates, quality diagnostics, and exact indicator labels.</p><span class="tag">EXPORT</span><br><a class="go" href="/dashboard/export">Open</a></div>
  <div class="card"><h2>Document Evidence Detail</h2><p class="muted">Inspect one indexed document's SHA-256 provenance, discovery linkage, structured claims, attribution, verification, trust, and supersession history. Private storage references remain redacted.</p><span class="tag">PROVENANCE</span><br><a class="go" href="/dashboard/document">Open</a></div>
  <div class="card"><h2>Provenance Graph</h2><p class="muted">Visualize evidence lineage from trusted source to indexed document, structured claims, attribution, verification/trust events, and supersession relationships.</p><span class="tag">LINEAGE</span><br><a class="go" href="/dashboard/provenance">Open</a></div>
  <div class="card"><h2>Conflict Investigation</h2><p class="muted">Inspect independently published values that disagree in the same exact entity, metric, unit, and persisted temporal scope without auto-resolving which value is correct.</p><span class="tag">CONFLICTS</span><br><a class="go" href="/dashboard/conflicts">Open</a></div>
  <div class="card"><h2>Verification Workbench</h2><p class="muted">Why claims remain candidate, conflicted, quality-failed, or independently corroborated. Read-only diagnostics only.</p><span class="tag">VERIFICATION</span><br><a class="go" href="/dashboard/verification">Open</a></div>
  <div class="card"><h2>Quality & Verification Coverage</h2><p class="muted">Per-source extraction-quality debt, missing temporal scope, publisher-independence coverage, exact comparable groups, and independent conflicts.</p><span class="tag">QUALITY</span><br><a class="go" href="/dashboard/quality-coverage">Open</a></div>
  <div class="card"><h2>Evidence Quality Scorecards</h2><p class="muted">Factual completeness dimensions for quality gates, temporal scope, attribution, document SHA provenance, raw evidence retention, source registry coverage, and exact indicator mapping. No composite truth score.</p><span class="tag">AUDIT</span><br><a class="go" href="/dashboard/quality-scorecards">Open</a></div>
  <div class="card"><h2>Economic Indicator Catalog</h2><p class="muted">Exact-alias canonical metric overlay with original persisted source labels preserved, expected units, categories, and mapping coverage.</p><span class="tag">NORMALIZATION</span><br><a class="go" href="/dashboard/indicator-catalog">Open</a></div>
  <div class="card"><h2>Evidence Timeline</h2><p class="muted">Chronological entity/metric evidence using only persisted effective/publication dates, including superseded and undated history.</p><span class="tag">HISTORY</span><br><a class="go" href="/dashboard/timeline">Open</a></div>
  <div class="card"><h2>Evidence Change Detection</h2><p class="muted">Factual differences between comparable dated evidence, including explicit supersessions and numeric increases/decreases when units match.</p><span class="tag">CHANGE</span><br><a class="go" href="/dashboard/changes">Open</a></div>
</div>
<div class="notice"><strong>Safety boundary:</strong> these pages are inspection/export surfaces only. They do not run ingestion, change scheduler cadence, mutate claim states, enable trust promotion, repair cloud stores, or delete evidence.</div>
</main></body></html>'''


@router.get(
    "/dashboard/hub",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def dashboard_hub() -> str:
    return DASHBOARD_HUB_HTML
