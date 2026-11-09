import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edu")

app = FastAPI(title="Edu SDR", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health():
    return {"ok": True, "service": "edu-sdr", "version": "0.1.0"}


@app.post("/webhooks/evolution")
async def evolution_webhook(request: Request):
    """Ingresso Evolution — por enquanto só registra o payload (orquestrador na próxima fase)."""
    payload = await request.json()
    event = payload.get("event") or payload.get("type")
    logger.info("evolution webhook event=%s keys=%s", event, list(payload.keys()))
    return JSONResponse({"ok": True, "received": True, "event": event})
