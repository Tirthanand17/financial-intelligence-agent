from fastapi import FastAPI, Request

from app.api.dashboard import router as dashboard_router
from app.api.dashboard_hub import router as dashboard_hub_router
from app.api.document_detail_dashboard import router as document_detail_dashboard_router
from app.api.quality_coverage_dashboard import router as quality_coverage_dashboard_router
from app.api.readiness_dashboard import router as readiness_dashboard_router
from app.api.routes import router
from app.api.timeline_dashboard import router as timeline_dashboard_router
from app.api.verification_dashboard import router as verification_dashboard_router
from app.security_headers import harden_response_headers

app = FastAPI(
    title="Financial Intelligence Agent",
    version="0.3.0",
    description="Continuously learning financial and economic intelligence system.",
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    return harden_response_headers(request, response)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
app.include_router(dashboard_router)
app.include_router(verification_dashboard_router)
app.include_router(timeline_dashboard_router)
app.include_router(readiness_dashboard_router)
app.include_router(quality_coverage_dashboard_router)
app.include_router(document_detail_dashboard_router)
app.include_router(dashboard_hub_router)
