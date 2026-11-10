"""Rotas públicas e painel da Fase 4 (interesse, leads, painel)."""

from __future__ import annotations

import secrets as py_secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings


def register_fase4_routes(app: FastAPI, *, admin_authorized) -> None:
    @app.get("/interesse", response_class=HTMLResponse)
    async def interesse_form():
        from app.course_facts import catalog_course_names

        courses = catalog_course_names()
        opts = "\n".join(f'<option value="{c}">{c}</option>' for c in courses)
        opts += '\n<option value="outro">Outro / ainda não sei</option>'
        return HTMLResponse(_INTERESSE_HTML.replace("{{OPTS}}", opts))

    @app.post("/leads")
    async def create_lead(request: Request):
        from app.inbound_leads import create_or_update_lead, validate_lead_payload

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "json_invalido"}, status_code=400)
        payload, err = validate_lead_payload(body if isinstance(body, dict) else {})
        if err or not payload:
            return JSONResponse({"ok": False, "error": err or "invalido"}, status_code=400)
        settings = get_settings()
        delay = float(getattr(settings, "primeiro_contato_delay_seconds", 45) or 45)
        return create_or_update_lead(settings, payload, stagger_seconds=delay)

    @app.post("/admin/leads/import")
    async def import_leads(request: Request):
        if not admin_authorized(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        from app.inbound_leads import import_leads_csv

        content_type = (request.headers.get("content-type") or "").lower()
        if "multipart" in content_type:
            form = await request.form()
            upload = form.get("file")
            raw = await upload.read() if upload is not None else b""
        else:
            raw = await request.body()
        settings = get_settings()
        gap = 45 if settings.demo_fast_followup else 60
        return import_leads_csv(settings, raw, base_stagger_seconds=45, gap_seconds=gap)

    @app.get("/admin/painel", response_class=HTMLResponse)
    async def painel_view(request: Request):
        if not admin_authorized(request):
            return HTMLResponse(_PAINEL_LOGIN_HTML, status_code=401)
        from app.painel import collect_painel

        data = collect_painel(get_settings())
        secret = (
            request.query_params.get("secret")
            or request.cookies.get("edu_admin_secret")
            or ""
        )
        html = _render_painel(data, secret)
        resp = HTMLResponse(html)
        if request.query_params.get("secret"):
            resp.set_cookie(
                "edu_admin_secret",
                request.query_params.get("secret") or "",
                httponly=True,
                samesite="lax",
            )
        return resp

    @app.post("/admin/leads/{phone}/retomar-negociacao")
    async def retomar_negociacao(phone: str, request: Request):
        """Sai do handoff de desconto e agenda retomada comercial (demo)."""
        if not admin_authorized(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        from app.desconto_negocio import exit_handoff_to_negociacao
        from app.followups import get_scheduler
        from app.memory import ConversationMemory
        from app.outbound_cadence import cancel_retomadas

        settings = get_settings()
        digits = "".join(ch for ch in phone if ch.isdigit())
        mem = ConversationMemory(settings)
        meta = mem.get_meta(digits)
        if not meta:
            return JSONResponse({"ok": False, "error": "lead_nao_encontrado"}, status_code=404)
        etapa = exit_handoff_to_negociacao(meta)
        sched = get_scheduler()
        cancel_retomadas(digits, sched)
        # Retomada em ~10s (demo): sem oferecer desconto de cara.
        import time

        sched.schedule_job(
            phone=digits,
            job_type="retomada",
            run_at=time.time() + 10,
            payload={
                "trigger": "comercial_retorno",
                "step": 1,
                "max_steps": 1,
            },
        )
        meta["proxima_retomada_at"] = time.time() + 10
        mem.set_meta(digits, meta)
        return {
            "ok": True,
            "phone": digits,
            "etapa": etapa,
            "desconto_negociacao_nivel": meta.get("desconto_negociacao_nivel"),
            "scheduled_in_seconds": 10,
        }

    @app.post("/admin/leads/{phone}/force-primeiro-contato")
    async def force_primeiro_contato(phone: str, request: Request):
        """Reagenda e/ou dispara primeiro contato (recuperação de demo)."""
        if not admin_authorized(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        from app.followups import get_scheduler
        from app.memory import ConversationMemory
        from app.outbound_cadence import schedule_primeiro_contato

        settings = get_settings()
        digits = "".join(ch for ch in phone if ch.isdigit())
        mem = ConversationMemory(settings)
        meta = mem.get_meta(digits)
        if not meta:
            return JSONResponse({"ok": False, "error": "lead_nao_encontrado"}, status_code=404)
        # Garante flags de form (caso meta antiga/parcial).
        meta["consentimento"] = True
        meta.setdefault("origem", "formulario")
        meta["opt_out"] = False
        meta["retomadas_paused"] = False
        meta.pop("active_send_blocked_reason", None)
        if meta.get("etapa") not in ("primeiro_contato", "abertura", "qualificacao"):
            meta["etapa"] = "primeiro_contato"
        sched = get_scheduler()
        # Limpa jobs corrompidos (type null) e pendentes do phone.
        sched.clear_for_phone(digits)
        schedule_primeiro_contato(digits, meta, sched, delay_seconds=8)
        mem.set_meta(digits, meta)
        return {
            "ok": True,
            "phone": digits,
            "etapa": meta.get("etapa"),
            "scheduled_in_seconds": 8,
        }

    @app.post("/admin/leads/{phone}/painel-action")
    async def painel_action(phone: str, request: Request):
        form = await request.form()
        secret = str(form.get("secret") or "")
        settings = get_settings()
        expected = settings.webhook_secret or ""
        ok = bool(expected and secret and py_secrets.compare_digest(secret, expected))
        if not ok and not admin_authorized(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        action = str(form.get("action") or "")
        from app.followups import get_scheduler
        from app.lead_state import ensure_lead_state
        from app.memory import ConversationMemory
        from app.outbound_cadence import cancel_retomadas

        mem = ConversationMemory(settings)
        digits = "".join(ch for ch in phone if ch.isdigit())
        meta = mem.get_meta(digits)
        ensure_lead_state(meta)
        if action == "pause":
            meta["retomadas_paused"] = True
            cancel_retomadas(digits, get_scheduler())
        elif action == "opt_out":
            meta["opt_out"] = True
            meta["retomadas_paused"] = True
            cancel_retomadas(digits, get_scheduler())
        elif action == "reset":
            meta["etapa"] = "qualificacao"
            meta["opt_out"] = False
            meta["retomadas_paused"] = False
        mem.set_meta(digits, meta)
        return RedirectResponse(url=f"/admin/painel?secret={secret}", status_code=303)


def _render_painel(data: dict, secret: str) -> str:
    ind = data["indicadores"]
    cols = []
    for etapa, cards in data["by_etapa"].items():
        items = []
        for c in cards:
            briefing = (c.get("briefing") or "")[:160]
            items.append(
                "<article>"
                f"<strong>{c['nome']}</strong><br/><small>{c['phone']}</small><br/>"
                f"<small>{c.get('curso') or '—'}</small><br/>"
                f"<small>origem: {c.get('origem')}</small>"
                f"<p style='font-size:.8rem;opacity:.85'>{briefing}</p>"
                f"<form style='display:flex;gap:.3rem;flex-wrap:wrap' method='post' "
                f"action='/admin/leads/{c['phone']}/painel-action'>"
                f"<input type='hidden' name='secret' value='{secret}'/>"
                "<button name='action' value='pause'>Pausar</button>"
                "<button name='action' value='opt_out'>Opt-out</button>"
                "<button name='action' value='reset'>Reset etapa</button>"
                "</form></article>"
            )
        body = "".join(items) or "<p class='empty'>—</p>"
        cols.append(
            f"<section><h2>{etapa} <span>({len(cards)})</span></h2>{body}</section>"
        )
    mats = []
    for m in data["matriculas"]:
        extra = ""
        if m.get("comprador_nome") and m.get("comprador_nome") != m.get("aluno_nome"):
            extra = f" (compra: {m.get('comprador_nome')})"
        mats.append(
            f"<li><strong>{m.get('aluno_nome') or '?'}</strong> — {m.get('curso')}"
            f"{extra} · {m.get('phone')}</li>"
        )
    hands = [
        f"<li>{h.get('nome')} ({h.get('phone')}) — {h.get('motivo')} · etapa {h.get('etapa')}</li>"
        for h in data["handoffs"]
    ]
    conv = " · ".join(
        f"{k}: {v}" for k, v in (ind.get("conversao_por_origem") or {}).items()
    ) or "—"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Painel do funil</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#0b1f18;color:#e9f5ef}}
header{{padding:1rem 1.25rem;border-bottom:1px solid #1e3d31;display:flex;flex-wrap:wrap;gap:1rem;align-items:end}}
.kpi{{background:#143528;padding:.7rem 1rem;border-radius:12px;min-width:7rem}}
.kpi b{{display:block;font-size:1.3rem}}
.board{{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(14rem,1fr);gap:.75rem;padding:1rem;overflow-x:auto}}
section{{background:#10291f;border-radius:14px;padding:.75rem;min-height:12rem}}
h2{{font-size:.95rem;margin:.2rem 0 .6rem;text-transform:capitalize}}
article{{background:#173828;border-radius:10px;padding:.65rem;margin:0 0 .5rem;font-size:.88rem}}
button{{font:inherit;font-size:.72rem;border:0;border-radius:8px;padding:.35rem .5rem;background:#2d8f63;color:#fff;cursor:pointer}}
.tabs{{padding:1rem 1.25rem}}
</style></head>
<body>
<header>
  <div><div style="opacity:.7;font-size:.75rem">Edu SDR · demo-v3</div>
  <div style="font-size:1.3rem;font-weight:700">Painel do funil</div></div>
  <div class="kpi"><span>Novos</span><b>{ind['leads_novos']}</b></div>
  <div class="kpi"><span>Negociação</span><b>{ind['em_negociacao']}</b></div>
  <div class="kpi"><span>Contratos</span><b>{ind['contratos_enviados']}</b></div>
  <div class="kpi"><span>Matrículas</span><b>{ind['matriculas']}</b></div>
  <div class="kpi"><span>Origens</span><b style="font-size:.85rem">{conv}</b></div>
</header>
<div class="board">{"".join(cols)}</div>
<div class="tabs">
  <h3>Matrículas</h3><ul>{"".join(mats) or "<li>Nenhuma</li>"}</ul>
  <h3>Encaminhamentos</h3><ul>{"".join(hands) or "<li>Nenhum</li>"}</ul>
</div>
</body></html>"""


_PAINEL_LOGIN_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Painel — login</title>
<style>body{font-family:Georgia,serif;background:#0f2f24;color:#eef6f1;display:grid;place-items:center;min-height:100vh;margin:0}
form{background:#163d30;padding:1.5rem;border-radius:16px;width:min(22rem,92vw)}
input,button{width:100%;padding:.75rem;margin:.4rem 0;border-radius:10px;border:0;font:inherit}
button{background:#2d8f63;color:#fff;font-weight:700;cursor:pointer}</style></head>
<body><form method="get"><h1>Painel do funil</h1>
<p>Senha admin (mesmo secret do deploy)</p>
<input type="password" name="secret" placeholder="senha" required/>
<button type="submit">Entrar</button></form></body></html>"""


_INTERESSE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Interesse — Polo Faveni Catanduva</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap" rel="stylesheet"/>
<style>
:root { --ink:#0f2f24; --leaf:#1f6b4a; --leaf2:#2d8f63; --line:#c5ddd0; }
* { box-sizing:border-box; }
body { margin:0; font-family:"DM Sans",system-ui,sans-serif; color:var(--ink);
  background: radial-gradient(1200px 600px at 10% -10%, #d9efe3 0%, transparent 55%),
              linear-gradient(165deg, #f4fbf7 0%, #e7f2ec 45%, #f7faf8 100%); min-height:100vh; }
.wrap { max-width:28rem; margin:0 auto; padding:1.5rem 1.1rem 3rem; }
.brand { font-family:"Fraunces",Georgia,serif; font-size:clamp(1.7rem,5vw,2.2rem); line-height:1.15; margin:0 0 .35rem; }
.sub { color:#3d5c4e; margin:0 0 1.4rem; font-size:1rem; }
form { background:#fff; border:1px solid var(--line); border-radius:18px; padding:1.25rem; box-shadow:0 12px 40px rgba(15,47,36,.06); }
label { display:block; font-size:.85rem; font-weight:600; margin:0.85rem 0 .35rem; }
input,select { width:100%; padding:.75rem .85rem; border:1px solid var(--line); border-radius:12px; font:inherit; background:#fbfefc; }
.consent { display:flex; gap:.65rem; align-items:flex-start; margin:1.1rem 0 1.3rem; font-size:.92rem; line-height:1.35; }
.consent input { width:auto; margin-top:.2rem; }
button { width:100%; border:0; border-radius:999px; padding:.95rem 1rem; font:inherit; font-weight:700;
  color:#fff; background:linear-gradient(135deg,var(--leaf),var(--leaf2)); cursor:pointer; }
button:disabled { opacity:.55; cursor:wait; }
.ok,.err { margin-top:1rem; padding:.85rem 1rem; border-radius:12px; display:none; }
.ok { background:#e5f7ec; color:#145c38; }
.err { background:#fdecea; color:#8a1f1a; }
.foot { margin-top:1.2rem; font-size:.8rem; color:#5a7367; text-align:center; }
</style>
</head>
<body>
<main class="wrap">
  <p style="letter-spacing:.08em;text-transform:uppercase;font-size:.72rem;color:var(--leaf);font-weight:700;margin:0 0 .5rem">Polo Faveni Catanduva</p>
  <h1 class="brand">Quero saber mais sobre a pós</h1>
  <p class="sub">Deixa seu WhatsApp — a Clara do polo te chama por lá, sem compromisso.</p>
  <form id="f">
    <label for="nome">Nome</label>
    <input id="nome" name="nome" required autocomplete="name" placeholder="Seu nome completo"/>
    <label for="whatsapp">WhatsApp</label>
    <input id="whatsapp" name="whatsapp" required inputmode="tel" placeholder="(17) 99999-9999"/>
    <label for="interesse">Área ou curso de interesse</label>
    <select id="interesse" name="interesse" required>
      <option value="" disabled selected>Selecione</option>
      {{OPTS}}
    </select>
    <label for="graduacao">Já concluiu a graduação?</label>
    <select id="graduacao" name="graduacao">
      <option value="">Prefiro falar depois</option>
      <option value="concluida">Sim, concluí</option>
      <option value="cursando">Ainda estou cursando</option>
      <option value="nao_tem">Ainda não tenho</option>
    </select>
    <label class="consent">
      <input type="checkbox" name="consentimento" id="consentimento" required/>
      <span>Aceito ser contatado pelo WhatsApp pelo Polo Faveni Catanduva.</span>
    </label>
    <button type="submit" id="btn">Enviar interesse</button>
    <div class="ok" id="ok">Pronto! Em breve a Clara te chama no WhatsApp.</div>
    <div class="err" id="err"></div>
  </form>
  <p class="foot">Demonstração Edu SDR · dados usados só para contato comercial com consentimento.</p>
</main>
<script>
const f=document.getElementById('f');
const ok=document.getElementById('ok');
const err=document.getElementById('err');
const btn=document.getElementById('btn');
f.addEventListener('submit', async (e) => {
  e.preventDefault();
  ok.style.display='none'; err.style.display='none';
  btn.disabled=true;
  const fd=new FormData(f);
  const body={
    nome: fd.get('nome'),
    telefone: fd.get('whatsapp'),
    origem: 'formulario',
    interesse: fd.get('interesse'),
    graduacao: fd.get('graduacao') || null,
    consentimento: fd.get('consentimento') === 'on'
  };
  try {
    const r=await fetch('/leads', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const j=await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || 'falha');
    ok.style.display='block'; f.reset();
  } catch (ex) {
    err.textContent = 'Não deu pra enviar: ' + (ex.message || ex);
    err.style.display='block';
  } finally { btn.disabled=false; }
});
</script>
</body></html>"""
