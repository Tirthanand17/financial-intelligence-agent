from fastapi import FastAPI

from app.api.dashboard import router as dashboard_router
from app.api.routes import router

app = FastAPI(
    title="Financial Intelligence Agent",
    version="0.3.0",
    description="Continuously learning financial and economic intelligence system.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
app.include_router(dashboard_router)
