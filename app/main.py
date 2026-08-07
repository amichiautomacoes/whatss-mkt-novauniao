from fastapi import FastAPI

from app.webhooks.dispatch_webhook import router as dispatch_router
from app.webhooks.evolution_webhook import router as evolution_router


app = FastAPI(title="WhatsApp Marketing Automation")
app.include_router(dispatch_router, prefix="/webhooks")
app.include_router(evolution_router, prefix="/webhooks")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
