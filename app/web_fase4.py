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
        try:
            etapa = exit_handoff_to_negociacao(meta)
        except ValueError as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "error": str(exc),
                    "etapa": meta.get("etapa"),
                    "handoff_reason": meta.get("handoff_reason"),
                },
                status_code=409,
            )
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
            mem.set_meta(digits, meta)
        elif action == "opt_out":
            meta["opt_out"] = True
            meta["retomadas_paused"] = True
            cancel_retomadas(digits, get_scheduler())
            mem.set_meta(digits, meta)
        elif action == "reset":
            meta["etapa"] = "qualificacao"
            meta["opt_out"] = False
            meta["retomadas_paused"] = False
            mem.set_meta(digits, meta)
        elif action == "clear":
            # Zera histórico + meta do lead (cenários de teste / demo).
            cancel_retomadas(digits, get_scheduler())
            mem.clear(digits)
        else:
            mem.set_meta(digits, meta)
        return RedirectResponse(url=f"/admin/painel?secret={secret}", status_code=303)


def _esc(text: object) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_lead_card(c: dict, secret: str, *, compact: bool = False) -> str:
    nome = _esc(c.get("nome"))
    phone = _esc(c.get("phone"))
    curso = _esc(c.get("curso") or "—")
    origem = _esc(c.get("origem") or "whatsapp")
    briefing = _esc((c.get("briefing") or "")[:120])
    badges = []
    if c.get("retomadas_paused"):
        badges.append('<span class="badge warn">pausado</span>')
    if c.get("opt_out"):
        badges.append('<span class="badge danger">opt-out</span>')
    badge_html = " ".join(badges)
    brief_html = f'<p class="brief">{briefing}</p>' if briefing and not compact else ""
    return f"""
    <article class="lead-card">
      <div class="lead-top">
        <div>
          <div class="lead-name">{nome}</div>
          <div class="lead-meta">{phone} · {origem}</div>
        </div>
        {badge_html}
      </div>
      <div class="lead-course">{curso}</div>
      {brief_html}
      <form class="lead-actions" method="post" action="/admin/leads/{phone}/painel-action">
        <input type="hidden" name="secret" value="{_esc(secret)}"/>
        <button type="submit" name="action" value="pause" class="btn ghost">Pausar</button>
        <button type="submit" name="action" value="reset" class="btn ghost">Reset etapa</button>
        <button type="submit" name="action" value="clear" class="btn danger"
          onclick="return confirm('Limpar toda a interação deste número? Histórico e estado serão apagados.');">
          Limpar interação
        </button>
      </form>
    </article>"""


def _render_painel(data: dict, secret: str) -> str:
    from app.painel import ETAPA_LABELS, FUNNEL_LEVELS

    ind = data["indicadores"]
    by_etapa = data.get("by_etapa") or {}
    labels = data.get("etapa_labels") or ETAPA_LABELS
    levels = data.get("levels") or FUNNEL_LEVELS

    level_blocks: list[str] = []
    for level_name, etapas in levels:
        cols: list[str] = []
        for etapa in etapas:
            cards = by_etapa.get(etapa) or []
            items = "".join(_render_lead_card(c, secret) for c in cards)
            if not items:
                items = '<p class="empty">Nenhum lead neste estágio</p>'
            label = labels.get(etapa, etapa)
            cols.append(
                f'<section class="stage">'
                f'<header class="stage-head"><h3>{_esc(label)}</h3>'
                f'<span class="count">{len(cards)}</span></header>'
                f'<div class="stage-body">{items}</div></section>'
            )
        level_blocks.append(
            f'<div class="level">'
            f'<div class="level-label">{_esc(level_name)}</div>'
            f'<div class="level-grid cols-{len(etapas)}">{"".join(cols)}</div>'
            f"</div>"
        )

    # Estágios fora do mapa padrão (ex.: nao_elegivel)
    known = {e for _, ets in levels for e in ets}
    extra_cols = []
    for etapa, cards in by_etapa.items():
        if etapa in known or not cards:
            continue
        items = "".join(_render_lead_card(c, secret) for c in cards)
        label = labels.get(etapa, etapa)
        extra_cols.append(
            f'<section class="stage">'
            f'<header class="stage-head"><h3>{_esc(label)}</h3>'
            f'<span class="count">{len(cards)}</span></header>'
            f'<div class="stage-body">{items}</div></section>'
        )
    if extra_cols:
        level_blocks.append(
            '<div class="level"><div class="level-label">Outros</div>'
            f'<div class="level-grid cols-3">{"".join(extra_cols)}</div></div>'
        )

    inter_rows = []
    for c in data.get("interacoes") or []:
        etapa = c.get("etapa") or ""
        inter_rows.append(
            "<tr>"
            f"<td><strong>{_esc(c.get('nome'))}</strong><div class='muted'>{_esc(c.get('phone'))}</div></td>"
            f"<td><span class='pill'>{_esc(labels.get(etapa, etapa))}</span></td>"
            f"<td>{_esc(c.get('curso') or '—')}</td>"
            f"<td>{_esc(c.get('origem') or '—')}</td>"
            f"<td class='actions-cell'>"
            f"<form method='post' action='/admin/leads/{_esc(c.get('phone'))}/painel-action'>"
            f"<input type='hidden' name='secret' value='{_esc(secret)}'/>"
            "<button type='submit' name='action' value='clear' class='btn danger sm'"
            " onclick=\"return confirm('Limpar toda a interação deste número?');\">"
            "Limpar interação</button></form></td>"
            "</tr>"
        )

    mats = []
    for m in data.get("matriculas") or []:
        extra = ""
        if m.get("comprador_nome") and m.get("comprador_nome") != m.get("aluno_nome"):
            extra = f" · compra: {_esc(m.get('comprador_nome'))}"
        mats.append(
            f"<li><strong>{_esc(m.get('aluno_nome') or '?')}</strong> — "
            f"{_esc(m.get('curso'))}{extra}"
            f"<div class='muted'>{_esc(m.get('phone'))}</div></li>"
        )
    hands = [
        f"<li><strong>{_esc(h.get('nome'))}</strong> — {_esc(h.get('motivo'))}"
        f"<div class='muted'>{_esc(h.get('phone'))} · {_esc(labels.get(h.get('etapa'), h.get('etapa')))}</div></li>"
        for h in data.get("handoffs") or []
    ]
    conv = " · ".join(
        f"{_esc(k)}: {v}" for k, v in (ind.get("conversao_por_origem") or {}).items()
    ) or "—"

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CRM · Funil comercial</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
:root {{
  --bg: #f4f6f9;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --accent: #1d4ed8;
  --accent-soft: #eff6ff;
  --danger: #b91c1c;
  --danger-soft: #fef2f2;
  --warn: #b45309;
  --warn-soft: #fffbeb;
  --ok: #047857;
  --shadow: 0 1px 2px rgba(15,23,42,.06), 0 8px 24px rgba(15,23,42,.04);
  --radius: 12px;
  --font: "IBM Plex Sans", system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; }}
body {{
  font-family: var(--font);
  color: var(--ink);
  background:
    radial-gradient(900px 420px at 100% -10%, #dbeafe 0%, transparent 55%),
    linear-gradient(180deg, #eef2f7 0%, var(--bg) 40%, #eef2f7 100%);
}}
a {{ color: var(--accent); }}
.shell {{ max-width: 1280px; margin: 0 auto; padding: 1.25rem 1.25rem 3rem; }}
.topbar {{
  display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;
  justify-content: space-between; margin-bottom: 1.25rem;
}}
.brand-block h1 {{
  margin: .15rem 0 0; font-size: 1.55rem; font-weight: 700; letter-spacing: -.02em;
}}
.brand-block p {{ margin: 0; color: var(--muted); font-size: .92rem; }}
.nav-pills {{ display: flex; gap: .5rem; flex-wrap: wrap; }}
.nav-pills a {{
  text-decoration: none; color: var(--ink); background: var(--surface);
  border: 1px solid var(--line); border-radius: 999px; padding: .45rem .85rem;
  font-size: .85rem; font-weight: 500; box-shadow: var(--shadow);
}}
.nav-pills a:hover {{ border-color: #bfdbfe; background: var(--accent-soft); }}
.kpis {{
  display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .75rem;
  margin-bottom: 1.35rem;
}}
.kpi {{
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: .9rem 1rem; box-shadow: var(--shadow);
}}
.kpi span {{ display: block; color: var(--muted); font-size: .78rem; font-weight: 500; }}
.kpi b {{ display: block; margin-top: .25rem; font-size: 1.45rem; font-weight: 700; font-variant-numeric: tabular-nums; }}
.kpi .sub {{ margin-top: .35rem; font-size: .75rem; color: var(--muted); line-height: 1.3; }}
.panel {{
  background: var(--surface); border: 1px solid var(--line); border-radius: 16px;
  box-shadow: var(--shadow); padding: 1rem 1.1rem 1.15rem; margin-bottom: 1rem;
}}
.panel-head {{
  display: flex; justify-content: space-between; align-items: baseline; gap: 1rem;
  margin-bottom: .85rem;
}}
.panel-head h2 {{ margin: 0; font-size: 1.05rem; font-weight: 650; }}
.panel-head p {{ margin: 0; color: var(--muted); font-size: .85rem; }}
.level {{ margin-bottom: 1rem; }}
.level:last-child {{ margin-bottom: 0; }}
.level-label {{
  font-size: .72rem; font-weight: 650; letter-spacing: .04em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 .45rem .15rem;
}}
.level-grid {{
  display: grid; gap: .65rem; align-items: start;
}}
.level-grid.cols-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
.level-grid.cols-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
.stage {{
  background: var(--surface-2); border: 1px solid var(--line); border-radius: 12px;
  min-height: 8.5rem; display: flex; flex-direction: column;
}}
.stage-head {{
  display: flex; justify-content: space-between; align-items: center;
  padding: .65rem .75rem; border-bottom: 1px solid var(--line);
}}
.stage-head h3 {{ margin: 0; font-size: .88rem; font-weight: 600; }}
.count {{
  min-width: 1.4rem; height: 1.4rem; border-radius: 999px; background: #e2e8f0;
  color: var(--ink); font-size: .72rem; font-weight: 700; display: grid; place-items: center;
  font-variant-numeric: tabular-nums;
}}
.stage-body {{ padding: .55rem; display: flex; flex-direction: column; gap: .45rem; max-height: 18rem; overflow: auto; }}
.lead-card {{
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: .6rem .65rem;
}}
.lead-top {{ display: flex; justify-content: space-between; gap: .5rem; align-items: flex-start; }}
.lead-name {{ font-size: .9rem; font-weight: 600; }}
.lead-meta {{ font-size: .72rem; color: var(--muted); margin-top: .1rem; }}
.lead-course {{ font-size: .78rem; color: #334155; margin-top: .35rem; }}
.brief {{ margin: .4rem 0 0; font-size: .72rem; color: var(--muted); line-height: 1.35; }}
.lead-actions {{ display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .55rem; }}
.btn {{
  font: inherit; font-size: .72rem; font-weight: 600; border-radius: 8px; border: 1px solid var(--line);
  padding: .32rem .55rem; background: var(--surface); color: var(--ink); cursor: pointer;
}}
.btn:hover {{ border-color: #cbd5e1; }}
.btn:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.btn.ghost {{ background: #fff; }}
.btn.danger {{ background: var(--danger-soft); color: var(--danger); border-color: #fecaca; }}
.btn.danger:hover {{ background: #fee2e2; }}
.btn.sm {{ padding: .28rem .5rem; }}
.badge {{
  font-size: .65rem; font-weight: 650; border-radius: 999px; padding: .12rem .4rem;
  text-transform: uppercase; letter-spacing: .03em;
}}
.badge.warn {{ background: var(--warn-soft); color: var(--warn); }}
.badge.danger {{ background: var(--danger-soft); color: var(--danger); }}
.empty {{ margin: .4rem; color: var(--muted); font-size: .8rem; }}
.muted {{ color: var(--muted); font-size: .75rem; }}
.grid-2 {{ display: grid; grid-template-columns: 1.4fr .9fr; gap: 1rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
th, td {{ text-align: left; padding: .65rem .4rem; border-bottom: 1px solid var(--line); vertical-align: middle; }}
th {{ color: var(--muted); font-size: .72rem; font-weight: 650; text-transform: uppercase; letter-spacing: .03em; }}
.pill {{
  display: inline-block; background: var(--accent-soft); color: #1e40af; border-radius: 999px;
  padding: .15rem .5rem; font-size: .72rem; font-weight: 600;
}}
.actions-cell form {{ margin: 0; }}
.side-list {{ list-style: none; margin: 0; padding: 0; }}
.side-list li {{ padding: .55rem 0; border-bottom: 1px solid var(--line); font-size: .88rem; }}
.side-list li:last-child {{ border-bottom: 0; }}
@media (max-width: 980px) {{
  .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .level-grid.cols-3, .level-grid.cols-4 {{ grid-template-columns: 1fr 1fr; }}
  .grid-2 {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 640px) {{
  .kpis {{ grid-template-columns: 1fr 1fr; }}
  .level-grid.cols-3, .level-grid.cols-4 {{ grid-template-columns: 1fr; }}
}}
::selection {{ background: #bfdbfe; }}
</style>
</head>
<body>
<main class="shell">
  <div class="topbar">
    <div class="brand-block">
      <h1>CRM comercial</h1>
      <p>Funil da Clara · visão operacional do atendimento</p>
    </div>
    <nav class="nav-pills">
      <a href="#funil">Funil</a>
      <a href="#teste">Teste / limpar</a>
      <a href="#registros">Matrículas &amp; handoffs</a>
      <a href="/interesse">Formulário público</a>
    </nav>
  </div>

  <section class="kpis" aria-label="Indicadores">
    <div class="kpi"><span>Leads ativos</span><b>{ind.get('total_leads', data.get('phones_scanned', 0))}</b></div>
    <div class="kpi"><span>Novos (24h)</span><b>{ind['leads_novos']}</b></div>
    <div class="kpi"><span>Em negociação</span><b>{ind['em_negociacao']}</b></div>
    <div class="kpi"><span>Contratos</span><b>{ind['contratos_enviados']}</b></div>
    <div class="kpi"><span>Matrículas</span><b>{ind['matriculas']}</b><div class="sub">{conv}</div></div>
  </section>

  <section class="panel" id="funil">
    <div class="panel-head">
      <div>
        <h2>Funil por estágio</h2>
        <p>Organizado em três níveis — entrada, negociação e fechamento.</p>
      </div>
    </div>
    {"".join(level_blocks)}
  </section>

  <section class="panel" id="teste">
    <div class="panel-head">
      <div>
        <h2>Números em interação</h2>
        <p>Use <strong>Limpar interação</strong> para zerar histórico e estado — ideal para testar vários cenários no mesmo chip.</p>
      </div>
    </div>
    <div style="overflow:auto">
      <table>
        <thead>
          <tr><th>Lead</th><th>Estágio</th><th>Curso / interesse</th><th>Origem</th><th></th></tr>
        </thead>
        <tbody>
          {"".join(inter_rows) or '<tr><td colspan="5" class="muted">Nenhuma interação no momento.</td></tr>'}
        </tbody>
      </table>
    </div>
  </section>

  <div class="grid-2" id="registros">
    <section class="panel">
      <div class="panel-head"><div><h2>Matrículas</h2><p>Confirmações de checkout demo.</p></div></div>
      <ul class="side-list">{"".join(mats) or '<li class="muted">Nenhuma matrícula ainda.</li>'}</ul>
    </section>
    <section class="panel">
      <div class="panel-head"><div><h2>Encaminhamentos</h2><p>Handoffs registrados para especialista.</p></div></div>
      <ul class="side-list">{"".join(hands) or '<li class="muted">Nenhum handoff aberto.</li>'}</ul>
    </section>
  </div>
</main>
</body>
</html>"""


_PAINEL_LOGIN_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CRM · acesso</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#1d4ed8; }
body {
  margin:0; min-height:100vh; display:grid; place-items:center;
  font-family:"IBM Plex Sans",system-ui,sans-serif; color:var(--ink);
  background: radial-gradient(700px 360px at 80% 0%, #dbeafe 0%, transparent 55%), #f4f6f9;
}
form {
  width:min(22rem,92vw); background:#fff; border:1px solid var(--line);
  border-radius:16px; padding:1.4rem 1.35rem 1.5rem;
  box-shadow:0 1px 2px rgba(15,23,42,.06), 0 12px 32px rgba(15,23,42,.06);
}
h1 { margin:0 0 .35rem; font-size:1.35rem; letter-spacing:-.02em; }
p { margin:0 0 1rem; color:var(--muted); font-size:.92rem; }
label { display:block; font-size:.8rem; font-weight:600; margin:0 0 .35rem; }
input,button { width:100%; font:inherit; border-radius:10px; padding:.75rem .85rem; }
input { border:1px solid var(--line); margin-bottom:.85rem; }
button { border:0; background:var(--accent); color:#fff; font-weight:650; cursor:pointer; }
button:hover { background:#1e40af; }
button:focus-visible { outline:2px solid #93c5fd; outline-offset:2px; }
</style>
</head>
<body>
<form method="get">
  <h1>CRM comercial</h1>
  <p>Entre com o secret admin do deploy para abrir o funil.</p>
  <label for="secret">Senha admin</label>
  <input id="secret" type="password" name="secret" placeholder="secret" required autocomplete="current-password"/>
  <button type="submit">Abrir painel</button>
</form>
</body>
</html>"""


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
