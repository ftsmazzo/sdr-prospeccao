import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.checkout import confirm_checkout, get_checkout
from app.config import get_settings
from app.followups import followup_worker
from app.inbound_buffer import get_inbound_buffer, inbound_worker
from app.orchestrator import Orchestrator
from app.webhook_parse import parse_incoming

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edu")


async def _process_batch(phone: str, batch: list[dict]) -> None:
    try:
        orch = Orchestrator(get_settings())
        merged = await orch.merge_inbound_batch(batch)
        await orch.handle_inbound(
            phone,
            merged["text"],
            push_name=merged.get("push_name") or "",
            has_audio=bool(merged.get("has_audio")),
            has_image=bool(merged.get("has_image")),
            has_document=bool(merged.get("has_document")),
            document_filename=merged.get("document_filename") or "",
            message_id=merged.get("message_id") or "",
            remote_jid=merged.get("remote_jid") or "",
        )
    except Exception:
        logger.exception("falha ao processar lote de %s", phone)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(followup_worker(stop), name="followup-worker"),
        asyncio.create_task(inbound_worker(stop, _process_batch), name="inbound-worker"),
    ]
    logger.info("workers followup + inbound criados")
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Edu SDR", version="0.7.7", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "service": "edu-sdr",
        "version": "0.7.7",
        "agent_name": settings.agent_name,
        "agent_gender": settings.agent_gender,
        "openrouter": bool(settings.openrouter_api_key),
        "evolution": bool(settings.evolution_api_key and settings.evolution_base_url),
        "elevenlabs": bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id),
        "followup_delay_seconds": settings.followup_delay_seconds,
        "webhook_secret_enforce": settings.webhook_secret_enforce,
        "inbound_debounce_seconds": settings.inbound_debounce_seconds,
        "handoff_max_objecoes": settings.handoff_max_objecoes,
        "redis": bool(settings.redis_url),
    }


def _admin_authorized(request: Request) -> bool:
    settings = get_settings()
    provided = request.headers.get("X-Admin-Secret") or ""
    expected = settings.webhook_secret or ""
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)


def _extract_webhook_secret(request: Request, path_secret: str | None = None) -> str:
    return (
        request.headers.get("X-Webhook-Secret")
        or (path_secret or "")
        or ""
    )


def _webhook_secret_ok(provided: str) -> tuple[bool, str]:
    """Retorna (allowed, reason). Com enforce=false, always allowed (pode avisar)."""
    settings = get_settings()
    expected = settings.webhook_secret or ""
    if not expected:
        if settings.webhook_secret_enforce:
            return False, "webhook_secret_not_configured"
        logger.warning("WEBHOOK_SECRET vazio — aceitando (enforce=false)")
        return True, "no_secret_configured"

    match = bool(provided) and secrets.compare_digest(provided, expected)
    if match:
        return True, "ok"

    if settings.webhook_secret_enforce:
        return False, "invalid_secret"

    logger.warning(
        "webhook secret missing/mismatch (enforce=false) — aceitando; provided=%s",
        "set" if provided else "empty",
    )
    return True, "mismatch_soft"


@app.get("/admin/followups")
async def list_followups(request: Request):
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    from app.followups import get_scheduler

    jobs = get_scheduler().list_pending()
    now = __import__("time").time()
    return {
        "ok": True,
        "count": len(jobs),
        "jobs": [
            {
                "id": j.get("id"),
                "phone": j.get("phone"),
                "course": j.get("course"),
                "lead_name": j.get("lead_name"),
                "has_cpf": bool(j.get("cpf")),
                "seconds_left": max(0, int((j.get("run_at") or 0) - now)),
                "with_checkout": j.get("with_checkout", True),
            }
            for j in jobs
        ],
    }


@app.get("/admin/leads/{phone}")
async def get_lead(phone: str, request: Request):
    """Snapshot do lead_state + etapa. Header: X-Admin-Secret."""
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    from app.lead_state import ensure_lead_state, summarize_lead
    from app.memory import ConversationMemory

    settings = get_settings()
    digits = phone.replace("+", "").replace(" ", "").replace("-", "")
    memory = ConversationMemory(settings)
    meta = memory.get_meta(digits)
    ensure_lead_state(meta)
    history = memory.get_history(digits)
    ls = meta.get("lead_state") or {}
    return {
        "ok": True,
        "phone": digits,
        "etapa": meta.get("etapa"),
        "lead_state": ls,
        "objecao_ativa": ls.get("objecao_ativa"),
        "pending_contract": bool(meta.get("pending_contract")),
        "contract_sent": bool(meta.get("contract_sent")),
        "desconto_respondido": bool(meta.get("desconto_respondido")),
        "handoff_reason": meta.get("handoff_reason"),
        "objecoes_sem_avanco": meta.get("objecoes_sem_avanco", 0),
        "full_name": meta.get("full_name"),
        "has_cpf": bool(meta.get("cpf")),
        "course": meta.get("course"),
        "history_len": len(history),
        "summary": summarize_lead(meta),
    }


@app.post("/admin/leads/{phone}/reset-etapa")
async def reset_lead_etapa(phone: str, request: Request):
    """Reinicia etapa do lead (default qualificacao). Header: X-Admin-Secret."""
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    from app.lead_state import ETAPAS, reset_etapa
    from app.memory import ConversationMemory

    settings = get_settings()
    digits = phone.replace("+", "").replace(" ", "").replace("-", "")
    etapa = (body.get("etapa") or "qualificacao").strip()
    if etapa not in ETAPAS:
        return JSONResponse(
            {"ok": False, "error": "etapa_invalida", "allowed": list(ETAPAS)},
            status_code=400,
        )

    memory = ConversationMemory(settings)
    meta = memory.get_meta(digits)
    reset_etapa(meta, etapa)
    memory.set_meta(digits, meta)
    return {
        "ok": True,
        "phone": digits,
        "etapa": meta.get("etapa"),
        "lead_state": meta.get("lead_state"),
        "objecoes_sem_avanco": meta.get("objecoes_sem_avanco", 0),
    }


@app.post("/admin/reset-memory")
async def reset_memory(request: Request):
    """Limpa histórico Redis + follow-ups. Header: X-Admin-Secret."""
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    settings = get_settings()
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    from app.followups import get_scheduler
    from app.memory import ConversationMemory

    memory = ConversationMemory(settings)
    scheduler = get_scheduler()
    phone = (body.get("phone") or "").strip()
    followups_only = bool(body.get("followups_only"))

    if phone:
        digits = phone.replace("+", "").replace(" ", "")
        followups = scheduler.clear_for_phone(digits)
        if followups_only:
            return {
                "ok": True,
                "scope": "phone_followups",
                "phone": digits,
                "followups_removed": followups,
            }
        cleared = memory.clear(digits)
        return {
            "ok": True,
            "scope": "phone",
            "phone": digits,
            "memory_cleared": cleared,
            "followups_removed": followups,
        }

    if followups_only:
        return {
            "ok": True,
            "scope": "followups_all",
            "followups_removed": scheduler.clear_all(),
        }

    return {
        "ok": True,
        "scope": "all",
        "memory_keys_removed": memory.clear_all(),
        "followups_removed": scheduler.clear_all(),
    }


async def _handle_evolution_webhook(request: Request, path_secret: str | None = None):
    provided = _extract_webhook_secret(request, path_secret)
    ok, reason = _webhook_secret_ok(provided)
    if not ok:
        return JSONResponse({"ok": False, "error": reason}, status_code=401)

    payload = await request.json()
    event = payload.get("event") or payload.get("type")
    logger.info("evolution webhook event=%s secret=%s", event, reason)

    incoming = parse_incoming(payload)
    if not incoming:
        return JSONResponse({"ok": True, "ignored": True, "event": event})

    get_inbound_buffer().enqueue(
        {
            "phone": incoming["phone"],
            "text": incoming.get("text") or "",
            "push_name": incoming.get("push_name") or "",
            "has_audio": bool(incoming.get("has_audio")),
            "has_image": bool(incoming.get("has_image")),
            "has_document": bool(incoming.get("has_document")),
            "document_filename": incoming.get("document_filename") or "",
            "message_id": incoming.get("message_id") or "",
            "remote_jid": incoming.get("remote_jid") or "",
            "media_message": incoming.get("media_message"),
        }
    )
    return JSONResponse({"ok": True, "queued": True, "debounced": True, "event": event})


@app.post("/webhooks/evolution")
async def evolution_webhook(request: Request):
    return await _handle_evolution_webhook(request)


@app.post("/webhooks/evolution/{path_secret}")
async def evolution_webhook_with_secret(path_secret: str, request: Request):
    return await _handle_evolution_webhook(request, path_secret=path_secret)


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
        <p style="color:#444;font-size:0.95rem">
          Documentos complementares (RG/CNH, diploma ou declaração, histórico)
          podem ser entregues <strong>depois</strong> desta confirmação.
        </p>
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
    try:
        from app.lead_state import ensure_lead_state
        from app.memory import ConversationMemory

        settings = get_settings()
        mem = ConversationMemory(settings)
        meta = mem.get_meta(session.phone)
        ensure_lead_state(meta)
        meta["etapa"] = "matriculado"
        meta["pending_contract"] = False
        mem.set_meta(session.phone, meta)
    except Exception:
        logger.exception("falha ao marcar matriculado phone=%s", getattr(session, "phone", ""))
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Matrícula confirmada</title></head>
<body style="font-family:Georgia,serif;background:#f7f4ef;padding:2.5rem 1.25rem;max-width:32rem;margin:0 auto">
  <h1>Matrícula registrada — demonstração</h1>
  <p>Pagamento simulado confirmado para <strong>{session.course_label}</strong>.</p>
  <p>Pode voltar ao WhatsApp — {get_settings().agent_name} continua te acompanhando.</p>
</body></html>"""
    )
