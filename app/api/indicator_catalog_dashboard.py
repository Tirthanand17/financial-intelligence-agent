from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.indicator_catalog import build_indicator_catalog_snapshot

router = APIRouter()


INDICATOR_CATALOG_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Economic Indicator Catalog</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1200px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:white;padding:10px 14px;border-radius:10px;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.chip{display:inline-block;background:#eef2ff;padding:5px 8px;border-radius:999px;font-size:11px;margin:3px}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.toolbar select{padding:9px;border:1px solid #d1d5db;border-radius:9px}button{border:0;background:#111827;color:#fff;border-radius:9px;padding:10px 14px}.item{border-left:4px solid #2563eb}.unmapped{border-left-color:#d97706}.safe{background:#ecfdf5;color:#166534;padding:12px 14px;border-radius:10px}.value{font-size:18px;font-weight:750;margin:6px 0}@media(max-width:700px){.top{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Economic Indicator Catalog</h1><p class="muted">Read-only canonical metric overlay. Original persisted source labels are preserved and unknown labels are never guessed.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/quality-coverage">Quality</a></div></div>
<div class="card toolbar"><label>Claim mappings <select id="limit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></label><button onclick="loadData()">Refresh</button><span id="generated" class="muted"></span></div>
<div class="grid"><div class="card"><div class="muted">Catalog indicators</div><div id="catalog" class="metric">-</div></div><div class="card"><div class="muted">Persisted claims</div><div id="claims" class="metric">-</div></div><div class="card"><div class="muted">Mapped claims</div><div id="mapped" class="metric">-</div></div><div class="card"><div class="muted">Unmapped claims</div><div id="unmappedCount" class="metric">-</div></div><div class="card"><div class="muted">Observed indicators</div><div id="observed" class="metric">-</div></div></div>
<div id="safety" class="safe"></div><h2>Catalog</h2><div id="indicators"></div><h2>Unmapped persisted metric labels</h2><div id="unmapped"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
async function loadData(){const limit=document.getElementById('limit').value;const r=await fetch('/dashboard/indicator-catalog/status?limit='+encodeURIComponent(limit),{cache:'no-store'});if(!r.ok){safety.textContent='Indicator catalog could not be loaded.';return;}const d=await r.json();catalog.textContent=d.summary.catalog_indicators;claims.textContent=d.summary.persisted_claims;mapped.textContent=d.summary.mapped_claims;unmappedCount.textContent=d.summary.unmapped_claims;observed.textContent=d.summary.observed_indicators;generated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();safety.textContent=d.safety.note;indicators.innerHTML=d.indicators.map(x=>`<div class="card item"><strong>${esc(x.canonical_metric)}</strong><div class="muted">${esc(x.indicator_id)} · ${esc(x.category)} · claims ${esc(x.claim_count)}</div><div>${(x.aliases||[]).map(a=>`<span class="chip">${esc(a)}</span>`).join('')}</div>${x.latest_observation?`<div class="value">Latest observed: ${esc(x.latest_observation.value_text)} ${esc(x.latest_observation.unit||'')}</div><div class="muted">${esc(x.latest_observation.source_id)} · source label: ${esc(x.latest_observation.source_metric)} · state: ${esc(x.latest_observation.state)}</div>`:'<div class="muted">No persisted observation yet.</div>'}</div>`).join('');unmapped.innerHTML=d.unmapped_metrics.map(x=>`<div class="card item unmapped"><strong>${esc(x.source_metric)}</strong><div class="muted">Persisted claims: ${esc(x.claim_count)} · intentionally unmapped until an exact catalog alias is reviewed.</div></div>`).join('')||'<div class="card muted">No unmapped metrics in the current persisted claim set.</div>';}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/indicator-catalog",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def indicator_catalog_page() -> str:
    return INDICATOR_CATALOG_HTML


@router.get(
    "/dashboard/indicator-catalog/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def indicator_catalog_status(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_indicator_catalog_snapshot(limit=limit)
