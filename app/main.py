import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.checkout import confirm_checkout, get_checkout
from app.config import get_settings
from app.followups import followup_worker
from app.orchestrator import Orchestrator
from app.webhook_parse import parse_incoming

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edu")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(followup_worker(stop), name="followup-worker")
    logger.info("follow-up worker task criada")
    try:
        yield
    finally:
        stop.set()
        await task


app = FastAPI(title="Edu SDR", version="0.3.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _orchestrator() -> Orchestrator:
    return Orchestrator(get_settings())


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "service": "edu-sdr",
        "version": "0.3.0",
        "openrouter": bool(settings.openrouter_api_key),
        "evolution": bool(settings.evolution_api_key and settings.evolution_base_url),
        "elevenlabs": bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id),
        "followup_delay_seconds": settings.followup_delay_seconds,
        "redis": bool(settings.redis_url),
    }


async def _process_message(
    phone: str,
    text: str,
    push_name: str,
    has_audio: bool,
    media_message: dict | None,
) -> None:
    try:
        orch = _orchestrator()
        await orch.handle_inbound(
            phone,
            text,
            push_name=push_name,
            has_audio=has_audio,
            media_message=media_message,
        )
    except Exception:
        logger.exception("falha ao processar mensagem de %s", phone)


@app.post("/webhooks/evolution")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    event = payload.get("event") or payload.get("type")
    logger.info("evolution webhook event=%s", event)

    incoming = parse_incoming(payload)
    if not incoming:
        return JSONResponse({"ok": True, "ignored": True, "event": event})

    background_tasks.add_task(
        _process_message,
        incoming["phone"],
        incoming["text"],
        incoming["push_name"],
        incoming["has_audio"],
        incoming.get("media_message"),
    )
    return JSONResponse({"ok": True, "queued": True, "event": event})


@app.get("/checkout/{token}", response_class=HTMLResponse)
def checkout_page(token: str):
    session = get_checkout(token)
    if not session:
        return HTMLResponse(
            "<!doctype html><html lang='pt-BR'><body style='font-family:system-ui;padding:2rem'>"
            "<h1>Link inválido</h1><p>Esta matrícula demo não foi encontrada.</p></body></html>",
            status_code=404,
        )

    nome = session.lead_name or "você"
    if session.confirmed:
        body = (
            f"<h1>Matrícula registrada — demonstração</h1>"
            f"<p>Obrigado, {nome}. Pagamento simulado confirmado para "
            f"<strong>{session.course_label}</strong>.</p>"
        )
    else:
        body = f"""
        <h1>Matrícula Faveni — pagamento simulado</h1>
        <p>Olá, {nome}.</p>
        <p><strong>Curso:</strong> {session.course_label}</p>
        <p><strong>Mensalidade:</strong> {session.amount_label}</p>
        <form method="post" action="/checkout/{token}/confirm">
          <button type="submit" style="padding:0.9rem 1.4rem;font-size:1rem;cursor:pointer;
            background:#0b6e4f;color:#fff;border:0;border-radius:8px">
            Confirmar pagamento (demo)
          </button>
        </form>
        <p style="margin-top:2rem;color:#666;font-size:0.9rem">
          Simulação para demonstração — sem cobrança real.
        </p>
        """

    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Matrícula Faveni — pagamento simulado</title>
</head>
<body style="font-family:Georgia,serif;background:#f7f4ef;color:#1c1c1c;margin:0">
  <main style="max-width:32rem;margin:0 auto;padding:2.5rem 1.25rem">{body}</main>
</body>
</html>"""
    )


@app.post("/checkout/{token}/confirm", response_class=HTMLResponse)
def checkout_confirm(token: str):
    session = confirm_checkout(token)
    if not session:
        return HTMLResponse("<h1>Link inválido</h1>", status_code=404)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Matrícula confirmada</title></head>
<body style="font-family:Georgia,serif;background:#f7f4ef;padding:2.5rem 1.25rem;max-width:32rem;margin:0 auto">
  <h1>Matrícula registrada — demonstração</h1>
  <p>Pagamento simulado confirmado para <strong>{session.course_label}</strong>.</p>
  <p>Pode voltar ao WhatsApp — o Edu continua te acompanhando.</p>
</body></html>"""
    )
