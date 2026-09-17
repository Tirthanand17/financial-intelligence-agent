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
  <div class="card"><h2>Intelligence Evidence</h2><p class="muted">Human-readable current structured evidence, source coverage, claim states, conflicts, and recent indexed documents.</p><span class="tag">INTELLIGENCE</span><br><a class="go" href="/dashboard/intelligence-view">Open</a></div>
  <div class="card"><h2>Verification Workbench</h2><p class="muted">Why claims remain candidate, conflicted, quality-failed, or independently corroborated. Read-only diagnostics only.</p><span class="tag">VERIFICATION</span><br><a class="go" href="/dashboard/verification">Open</a></div>
  <div class="card"><h2>Quality & Verification Coverage</h2><p class="muted">Per-source extraction-quality debt, missing temporal scope, publisher-independence coverage, exact comparable groups, and independent conflicts.</p><span class="tag">QUALITY</span><br><a class="go" href="/dashboard/quality-coverage">Open</a></div>
  <div class="card"><h2>Evidence Timeline</h2><p class="muted">Chronological entity/metric evidence using only persisted effective/publication dates, including superseded and undated history.</p><span class="tag">HISTORY</span><br><a class="go" href="/dashboard/timeline">Open</a></div>
</div>
<div class="notice"><strong>Safety boundary:</strong> these pages are inspection surfaces only. They do not run ingestion, change scheduler cadence, mutate claim states, enable trust promotion, repair cloud stores, or delete evidence.</div>
</main></body></html>'''


@router.get(
    "/dashboard/hub",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def dashboard_hub() -> str:
    return DASHBOARD_HUB_HTML
