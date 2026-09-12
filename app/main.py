from fastapi import FastAPI

app = FastAPI(
    title="Financial Intelligence Agent",
    version="0.1.0",
    description="Continuously learning financial and economic intelligence system.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
