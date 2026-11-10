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
from app.web_fase4 import register_fase4_routes
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


app = FastAPI(title="Edu SDR", version="0.10.1", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "service": "edu-sdr",
        "version": "0.10.0",
        "agent_name": settings.agent_name,
        "agent_gender": settings.agent_gender,
        "openrouter": bool(settings.openrouter_api_key),
        "evolution": bool(settings.evolution_api_key and settings.evolution_base_url),
        "elevenlabs": bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id),
        "followup_delay_seconds": settings.followup_delay_seconds,
        "webhook_secret_enforce": settings.webhook_secret_enforce,
        "inbound_debounce_seconds": settings.inbound_debounce_seconds,
        "handoff_max_objecoes": settings.handoff_max_objecoes,
        "briefing_model": settings.briefing_model,
        "prompt_history_messages": settings.prompt_history_messages,
        "demo_fast_followup": bool(settings.demo_fast_followup),
        "active_send_daily_limit": settings.active_send_daily_limit,
        "redis": bool(settings.redis_url),
        "tag": "demo-v3",
    }


def _admin_authorized(request: Request) -> bool:
    settings = get_settings()
    provided = (
        request.headers.get("X-Admin-Secret")
        or request.cookies.get("edu_admin_secret")
        or request.query_params.get("secret")
        or ""
    )
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
                "type": j.get("type"),
                "phone": j.get("phone"),
                "course": j.get("course"),
                "lead_name": j.get("lead_name"),
                "trigger": j.get("trigger"),
                "has_cpf": bool(j.get("cpf")),
                "seconds_left": max(0, int((j.get("run_at") or 0) - now)),
                "with_checkout": j.get("with_checkout", True),
            }
            for j in jobs
        ],
    }


@app.get("/admin/handoffs")
async def list_handoffs(request: Request):
    """Lista pedidos de encaminhamento a especialista. Header: X-Admin-Secret."""
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    from app.handoff_requests import list_handoff_requests

    items = list_handoff_requests(get_settings())
    return {"ok": True, "count": len(items), "handoffs": items}


@app.get("/admin/handoffs/view", response_class=HTMLResponse)
async def view_handoffs(request: Request):
    """Página HTML simples para demo. Header: X-Admin-Secret."""
    if not _admin_authorized(request):
        return HTMLResponse("<h1>unauthorized</h1>", status_code=401)
    from datetime import datetime, timezone

    from app.handoff_requests import list_handoff_requests

    items = list_handoff_requests(get_settings())
    rows = []
    for h in items:
        ts = h.get("updated_at") or h.get("created_at") or 0
        try:
            when = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except (TypeError, ValueError, OSError):
            when = str(ts)
        summary = (h.get("lead_summary") or {}) if isinstance(h.get("lead_summary"), dict) else {}
        briefing = str(summary.get("briefing") or "")[:280]
        rows.append(
            "<tr>"
            f"<td>{h.get('nome') or '—'}</td>"
            f"<td>{h.get('phone') or '—'}</td>"
            f"<td>{h.get('motivo') or '—'}</td>"
            f"<td>{h.get('curso') or '—'}</td>"
            f"<td>{h.get('status') or '—'}</td>"
            f"<td>{when}</td>"
            f"<td>{briefing or '—'}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='7'>Nenhum pedido</td></tr>"
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Handoffs — Edu SDR</title>
<style>
body{{font-family:Georgia,serif;margin:2rem;background:#f7f4ef;color:#1c1c1c}}
table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #ddd;padding:.6rem;text-align:left;font-size:.95rem}}
th{{background:#eee}}
</style></head><body>
<h1>Pedidos de especialista</h1>
<p>{len(items)} registro(s)</p>
<table>
<thead><tr><th>Nome</th><th>Telefone</th><th>Motivo</th><th>Curso</th><th>Status</th><th>Atualizado</th><th>Briefing</th></tr></thead>
<tbody>{body}</tbody>
</table>
</body></html>"""
    )


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
        "matriculas": meta.get("matriculas") or [],
        "compra_atual": meta.get("compra_atual"),
        "briefing": meta.get("briefing") or "",
        "pending_offer": meta.get("pending_offer"),
        "origem": meta.get("origem"),
        "consentimento": bool(meta.get("consentimento")),
        "opt_out": bool(meta.get("opt_out")),
        "interesse": meta.get("interesse"),
        "active_sends": meta.get("active_sends") or [],
        "active_send_blocked_reason": meta.get("active_send_blocked_reason"),
        "proxima_retomada_at": meta.get("proxima_retomada_at"),
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


@app.post("/admin/leads/{phone}/rewind")
async def rewind_lead(phone: str, request: Request):
    """Corta o histórico a partir de um trecho e restaura etapa (ex.: matriculado).

    Body JSON:
      needle: texto a achar na 1ª msg (default \"esposa\")
      etapa: etapa destino (default \"matriculado\")
    Mantém matriculas[] / full_name / cpf. Limpa flags de aluno terceiro.
    Header: X-Admin-Secret.
    """
    if not _admin_authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    body: dict = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    from app.lead_state import ETAPAS, ensure_lead_state
    from app.memory import ConversationMemory

    settings = get_settings()
    digits = phone.replace("+", "").replace(" ", "").replace("-", "")
    needle = str(body.get("needle") or "esposa").strip().casefold()
    etapa = str(body.get("etapa") or "matriculado").strip()
    if etapa not in ETAPAS:
        return JSONResponse(
            {"ok": False, "error": "etapa_invalida", "allowed": list(ETAPAS)},
            status_code=400,
        )
    if not needle:
        return JSONResponse({"ok": False, "error": "needle_vazio"}, status_code=400)

    memory = ConversationMemory(settings)
    history = memory.get_history(digits)
    cut_at = None
    for i, msg in enumerate(history):
        if needle in str(msg.get("content") or "").casefold():
            cut_at = i
            break
    meta = memory.get_meta(digits)
    ls = ensure_lead_state(meta)
    force_meta = bool(body.get("force_meta"))
    kept = history
    if cut_at is None:
        if not force_meta:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "needle_nao_encontrado",
                    "phone": digits,
                    "history_len": len(history),
                },
                status_code=404,
            )
    else:
        kept = history[:cut_at]
        memory.replace_history(digits, kept)

    matriculas = list(meta.get("matriculas") or [])
    enrolled_course = None
    for item in matriculas:
        if isinstance(item, dict) and item.get("curso"):
            enrolled_course = str(item["curso"])
            break
    if not enrolled_course and meta.get("course"):
        enrolled_course = str(meta["course"])
    if enrolled_course and not matriculas:
        matriculas = [
            {
                "curso": enrolled_course,
                "aluno_nome": meta.get("full_name") or ls.get("nome"),
                "status": "confirmada",
            }
        ]
    if matriculas:
        meta["matriculas"] = matriculas
    if enrolled_course:
        meta["course"] = enrolled_course

    ls["aluno_e_terceiro"] = False
    ls["aluno_nome"] = None
    ls["aluno_relacao"] = None
    ls["aluno_genero"] = None
    ls["curso_recomendado"] = enrolled_course
    ls["curso_escolhido"] = enrolled_course
    ls["curso_alternativo"] = None
    ls["aceite_matricula"] = bool(enrolled_course)
    ls["proximo_passo"] = None
    ls["objecao_ativa"] = None
    meta["lead_state"] = ls
    meta["etapa"] = etapa
    meta["pending_contract"] = False
    meta["contract_sent"] = False
    meta.pop("pending_offer", None)
    meta.pop("_reopen_purchase", None)
    meta["stock_streak"] = 0
    memory.set_meta(digits, meta)

    return {
        "ok": True,
        "phone": digits,
        "cut_at": cut_at,
        "history_before": len(history),
        "history_after": len(kept),
        "etapa": meta.get("etapa"),
        "matriculas": meta.get("matriculas") or [],
        "aluno_e_terceiro": False,
        "curso_escolhido": ls.get("curso_escolhido"),
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

    from app.notify import is_internal_number, parse_notify_numbers

    settings = get_settings()
    if is_internal_number(
        str(incoming.get("phone") or ""),
        parse_notify_numbers(settings.handoff_notify_numbers),
    ):
        logger.info(
            "webhook ignorado — número interno phone=%s", incoming.get("phone")
        )
        return JSONResponse({"ok": True, "ignored": True, "reason": "internal_number"})

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
    from app.pricing import lookup_course_hours, price_for_course

    session = get_checkout(token)
    if not session:
        return HTMLResponse(
            "<!doctype html><html lang='pt-BR'><body style='font-family:system-ui;padding:2rem'>"
            "<h1>Link inválido</h1><p>Esta matrícula demo não foi encontrada.</p></body></html>",
            status_code=404,
        )

    nome = session.lead_name or "você"
    hours = lookup_course_hours(session.course_label)
    band = price_for_course(session.course_label)
    hours_html = f"{hours}h" if hours else "conforme catálogo"
    if band:
        valores_html = (
            f"<li>Mensalidade: <strong>{band.monthly_label}</strong></li>"
            f"<li>Total em 18x: <strong>{band.total_18_label}</strong></li>"
            f"<li>À vista: <strong>{band.a_vista_label}</strong></li>"
        )
    else:
        valores_html = f"<li>Mensalidade: <strong>{session.amount_label}</strong></li>"

    if session.confirmed:
        body = (
            f"<p class='brand'>Faveni Polo Catanduva</p>"
            f"<h1>Matrícula registrada — demonstração</h1>"
            f"<p>Obrigado, {nome}. Pagamento simulado confirmado para "
            f"<strong>{session.course_label}</strong>.</p>"
        )
    else:
        body = f"""
        <p class="brand">Faveni Polo Catanduva</p>
        <h1>Matrícula — pagamento simulado</h1>
        <p>Olá, {nome}.</p>
        <p><strong>Curso:</strong> {session.course_label}</p>
        <p><strong>Carga horária:</strong> {hours_html}</p>
        <ul style="padding-left:1.2rem;line-height:1.6">{valores_html}</ul>
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
  <style>.brand{{font-size:0.85rem;letter-spacing:0.04em;text-transform:uppercase;
  color:#0b6e4f;margin:0 0 0.5rem}}</style>
</head>
<body style="font-family:Georgia,serif;background:#f7f4ef;color:#1c1c1c;margin:0">
  <main style="max-width:32rem;margin:0 auto;padding:2.5rem 1.25rem">{body}</main>
</body>
</html>"""
    )


@app.post("/checkout/{token}/confirm", response_class=HTMLResponse)
async def checkout_confirm(token: str):
    session = confirm_checkout(token)
    if not session:
        return HTMLResponse("<h1>Link inválido</h1>", status_code=404)
    try:
        from datetime import datetime, timezone

        from app.clients.evolution import EvolutionClient
        from app.lead_state import ensure_lead_state
        from app.memory import ConversationMemory

        settings = get_settings()
        mem = ConversationMemory(settings)
        meta = mem.get_meta(session.phone)
        ls = ensure_lead_state(meta)
        meta["etapa"] = "matriculado"
        meta["pending_contract"] = False
        from app.contract_party import resolve_contract_party

        party = resolve_contract_party(meta, ls)
        aluno = (
            session.lead_name
            or party.get("aluno_nome")
            or ls.get("aluno_nome")
            or ""
        ).strip()
        comprador = (
            party.get("comprador_nome") or ls.get("nome") or ""
        ).strip()
        matriculas = list(meta.get("matriculas") or [])
        if not isinstance(matriculas, list):
            matriculas = []
        matriculas.append(
            {
                "curso": session.course_label,
                "aluno_nome": aluno or None,
                "comprador_nome": comprador or None,
                "status": "confirmada",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        meta["matriculas"] = matriculas
        # Encerra compra_atual ativa (se houver).
        ca = meta.get("compra_atual")
        if isinstance(ca, dict):
            ca["active"] = False
            ca["aceite"] = True
            ca["curso_escolhido"] = session.course_label
            meta["compra_atual"] = ca
        mem.set_meta(session.phone, meta)
        welcome = (
            f"Boa notícia — matrícula confirmada na pós em {session.course_label}"
            + (f" ({aluno})" if aluno else "")
            + "! O acesso ao AVA chega em até 2 dias úteis por e-mail e WhatsApp. "
            "Documentos complementares você pode mandar por aqui depois. "
            "Tutoria/suporte das 8h às 21h45. Qualquer dúvida, me chama."
        )
        try:
            evo = EvolutionClient(settings)
            await evo.send_text(session.phone, welcome, delay_ms=0)
            mem.append(session.phone, "assistant", welcome)
            if settings.handoff_notify_on_matricula:
                from app.notify import (
                    build_matricula_notify_message,
                    notify_numbers,
                    parse_notify_numbers,
                )

                nums = parse_notify_numbers(settings.handoff_notify_numbers)
                note = build_matricula_notify_message(
                    agent_name=settings.agent_name,
                    lead_nome=aluno or ls.get("nome"),
                    lead_phone=session.phone,
                    curso=session.course_label,
                    aluno_nome=aluno,
                    comprador_nome=comprador,
                )
                await notify_numbers(
                    evo, nums, note, exclude_phone=session.phone
                )
        except Exception:
            logger.exception(
                "falha ao enviar boas-vindas WhatsApp phone=%s", session.phone
            )
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


register_fase4_routes(app, admin_authorized=_admin_authorized)
