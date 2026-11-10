"""Cadência de retomada e primeiro contato."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger("edu.outbound_cadence")

# Delays padrão (segundos). DEMO_FAST_FOLLOWUP encurta.
_DEFAULT_DELAYS = {
    "funil_silence": (3 * 3600, 24 * 3600, 72 * 3600),  # 3h, 24h, 72h
    "vou_pensar": (2 * 24 * 3600,),  # 2 dias se sem data
    "contrato": (24 * 3600, 72 * 3600),
    "primeiro_contato": (24 * 3600, 72 * 3600),
}

_DEMO_DELAYS = {
    "funil_silence": (180, 600, 1200),  # 3 / 10 / 20 min — menos agressivo
    "vou_pensar": (180,),
    "contrato": (240, 600),
    # Uma só retomada após primeiro contato (evita rajada de 2 msgs)
    "primeiro_contato": (300,),
}

_THINK_DATE_RE = re.compile(
    r"(?i)\b("
    r"semana\s+que\s+vem|pr[oó]xima\s+semana|depois\s+de\s+amanh[aã]|"
    r"amanh[aã]|daqui\s+a\s+(\d+)\s+dias?"
    r")\b"
)


def cadence_delays(settings: Settings | None = None) -> dict[str, tuple[int, ...]]:
    s = settings or get_settings()
    if getattr(s, "demo_fast_followup", False):
        return dict(_DEMO_DELAYS)
    return dict(_DEFAULT_DELAYS)


def cancel_retomadas(phone: str, scheduler: Any) -> int:
    return scheduler.clear_for_phone(
        phone, types={"retomada", "primeiro_contato", "outbound_active"}
    )


def schedule_silence_followups(
    phone: str, meta: dict[str, Any], scheduler: Any, *, settings: Settings | None = None
) -> None:
    """Agenda 3 retomadas se o lead parar no meio do funil."""
    s = settings or get_settings()
    etapa = meta.get("etapa") or ""
    if etapa in (
        "matriculado",
        "aluno_atual",
        "esfriou",
        "nao_elegivel",
        "handoff_humano",
        "primeiro_contato",
    ):
        return
    if meta.get("opt_out") or meta.get("retomadas_paused"):
        return
    cancel_retomadas(phone, scheduler)
    delays = cadence_delays(s)["funil_silence"]
    now = time.time()
    for i, d in enumerate(delays):
        scheduler.schedule_job(
            phone=phone,
            job_type="retomada",
            run_at=now + d,
            payload={
                "trigger": f"silence_{i + 1}",
                "step": i + 1,
                "max_steps": len(delays),
            },
        )
    meta["proxima_retomada_at"] = now + delays[0]
    meta["retomada_step"] = 0


def schedule_primeiro_contato(
    phone: str, meta: dict[str, Any], scheduler: Any, *, delay_seconds: float = 45
) -> None:
    """Primeira mensagem ativa em até ~60s (+ follow-ups se sem resposta)."""
    cancel_retomadas(phone, scheduler)
    now = time.time()
    scheduler.schedule_job(
        phone=phone,
        job_type="primeiro_contato",
        run_at=now + max(5, delay_seconds),
        payload={"trigger": "primeiro_contato", "step": 0},
    )
    s = get_settings()
    delays = cadence_delays(s)["primeiro_contato"]
    for i, d in enumerate(delays):
        scheduler.schedule_job(
            phone=phone,
            job_type="retomada",
            run_at=now + delay_seconds + d,
            payload={
                "trigger": f"primeiro_contato_silence_{i + 1}",
                "step": i + 1,
                "max_steps": len(delays),
                "from_primeiro_contato": True,
            },
        )
    meta["proxima_retomada_at"] = now + delay_seconds


def schedule_contract_followups(
    phone: str, meta: dict[str, Any], scheduler: Any
) -> None:
    if (meta.get("etapa") or "") == "matriculado" or meta.get("retomadas_paused"):
        cancel_retomadas(phone, scheduler)
        meta["proxima_retomada_at"] = None
        return
    s = get_settings()
    delays = cadence_delays(s)["contrato"]
    now = time.time()
    # Não cancela o contrato job — só retomadas.
    scheduler.clear_for_phone(phone, types={"retomada"})
    for i, d in enumerate(delays):
        scheduler.schedule_job(
            phone=phone,
            job_type="retomada",
            run_at=now + d,
            payload={
                "trigger": f"contrato_{i + 1}",
                "step": i + 1,
                "max_steps": len(delays),
            },
        )
    meta["proxima_retomada_at"] = now + delays[0]


def parse_think_delay_seconds(text: str, *, settings: Settings | None = None) -> float:
    """Interpreta 'semana que vem' / 'amanhã' / 'daqui a N dias'."""
    s = settings or get_settings()
    demo = bool(getattr(s, "demo_fast_followup", False))
    t = text or ""
    m = _THINK_DATE_RE.search(t)
    if not m:
        return float(cadence_delays(s)["vou_pensar"][0])
    raw = m.group(0).casefold()
    if "semana" in raw:
        return 180.0 if demo else float(7 * 24 * 3600)
    if "amanhã" in raw or "amanha" in raw:
        if "depois" in raw:
            return 120.0 if demo else float(2 * 24 * 3600)
        return 90.0 if demo else float(24 * 3600)
    n = m.group(2)
    if n:
        days = max(1, int(n))
        return float(days * 60) if demo else float(days * 24 * 3600)
    return float(cadence_delays(s)["vou_pensar"][0])


def schedule_think_followup(
    phone: str,
    meta: dict[str, Any],
    scheduler: Any,
    *,
    user_text: str = "",
) -> float:
    delay = parse_think_delay_seconds(user_text)
    cancel_retomadas(phone, scheduler)
    run_at = time.time() + delay
    scheduler.schedule_job(
        phone=phone,
        job_type="retomada",
        run_at=run_at,
        payload={"trigger": "vou_pensar", "step": 1, "max_steps": 1},
    )
    meta["proxima_retomada_at"] = run_at
    return delay


async def compose_active_message(
    settings: Settings,
    phone: str,
    meta: dict[str, Any],
    job: dict[str, Any],
) -> str:
    """Gera texto de primeiro contato / retomada via LLM (com fallbacks)."""
    from app.clients.openrouter import OpenRouterClient
    from app.lead_state import ensure_lead_state

    ls = ensure_lead_state(meta)
    jtype = str(job.get("type") or "")
    trigger = str(job.get("trigger") or "")
    if (meta.get("etapa") or "") == "matriculado" or meta.get("retomadas_paused"):
        return ""
    briefing = str(meta.get("briefing") or "")
    interesse = (
        meta.get("interesse")
        or ls.get("area_interesse")
        or ls.get("curso_recomendado")
        or "pós-graduação"
    )
    origem = meta.get("origem") or "formulário"
    nome = ls.get("nome") or meta.get("full_name") or ""
    first = str(nome).split()[0] if nome else ""
    agent = settings.agent_name or "Clara"

    graduacao = str(ls.get("graduacao") or "").strip().casefold()

    def _primeiro_contato_fallback() -> str:
        greet = f"Oi{', ' + first if first else ''}! "
        base = (
            f"{greet}Sou a {agent}, do Polo Faveni Catanduva. "
            f"Vi pelo {origem} seu interesse na pós em {interesse}. "
        )
        if graduacao == "concluida":
            return (
                base
                + "Vi que você já concluiu a graduação — ótimo. "
                "Qual seu principal objetivo com essa especialização: "
                "atuar na área, crescer no trabalho atual ou mudar de carreira?"
            )
        if graduacao == "cursando":
            return (
                base
                + "Vi que você ainda está na graduação. A pós exige diploma "
                "ou declaração de conclusão — quer que eu te oriente no que dá "
                "para preparar agora, ou prefere falar quando estiver concluindo?"
            )
        if graduacao in ("nao_tem", "nao", "não"):
            return (
                base
                + "Vi que você ainda não tem graduação. A pós vem depois da "
                "faculdade — posso te ajudar a entender o caminho até lá, "
                "ou tem alguma dúvida específica sobre a área?"
            )
        return (
            base
            + "Para eu te orientar certinho na matrícula: você já concluiu "
            "a graduação?"
        )

    # Fallback sem LLM (testes / falha de API)
    def _fallback() -> str:
        if jtype == "primeiro_contato":
            return _primeiro_contato_fallback()
        curso = ls.get("curso_escolhido") or ls.get("curso_recomendado") or interesse
        etapa = meta.get("etapa") or ""
        step = int(job.get("step") or 0)
        if meta.get("comercial_retorno") and step <= 1:
            return (
                f"{first + ', ' if first else ''}consegui retomar seu caso da pós "
                f"em {curso} aqui no polo. Ainda faz sentido a gente continuar "
                "de onde paramos?"
            )
        if "contrato" in trigger:
            return (
                f"{first + ', ' if first else ''}conseguiu olhar o contrato da pós "
                f"em {curso}? Qualquer dúvida eu te ajudo por aqui."
            )
        if etapa == "fechamento":
            return (
                f"{first + ', ' if first else ''}quando quiser a gente retoma os dados "
                f"pra eu preparar o contrato de {curso}. Prefere seguir agora?"
            )
        if step <= 1:
            return (
                f"{first + ', ' if first else ''}retomando a conversa sobre a pós "
                f"em {curso}: ainda está no seu radar se matricular?"
            )
        return (
            f"{first + ', ' if first else ''}só pra não te perder: sobre a pós "
            f"em {curso}, prefere que eu te ajude com valor/condição ou com o "
            "próximo passo da matrícula?"
        )

    if not settings.openrouter_api_key:
        return _fallback()

    try:
        llm = OpenRouterClient(settings)
        envios = meta.get("active_sends") or []
        enviados = "; ".join(
            str(e.get("text") or "")[:80]
            for e in envios[-3:]
            if isinstance(e, dict)
        ) or "(nenhum envio ativo anterior)"
        if jtype == "primeiro_contato":
            if graduacao == "concluida":
                ask_rule = (
                    "A graduação JÁ CONSTA como concluída no formulário — "
                    "NÃO pergunte se concluiu. Agradeça/reconheça isso em 1 frase "
                    "e faça UMA pergunta sobre objetivo com a especialização "
                    "(atuar na área, crescer no emprego, mudar de carreira)."
                )
            elif graduacao == "cursando":
                ask_rule = (
                    "No formulário a pessoa ainda está CURSANDO a graduação — "
                    "NÃO pergunte se já concluiu. Reconheça isso e explique "
                    "em 1 frase que a pós exige diploma/declaração; pergunte se "
                    "quer orientação agora ou quando estiver concluindo."
                )
            elif graduacao in ("nao_tem", "nao", "não"):
                ask_rule = (
                    "No formulário a pessoa AINDA NÃO TEM graduação — "
                    "NÃO ofereça matrícula de pós agora. Reconheça o interesse "
                    "e pergunte se quer entender o caminho até a pós ou tirar "
                    "dúvida da área."
                )
            else:
                ask_rule = (
                    "Graduação desconhecida: faça UMA pergunta se já concluiu "
                    "a graduação (necessária para a pós)."
                )
            system = (
                f"Você é {agent}, consultora de matrículas do Polo Faveni Catanduva. "
                "Escreva a PRIMEIRA mensagem de WhatsApp (tom humano, curto, natural — "
                "não robotizado, sem 'estou à disposição' genérico). "
                f"Apresente-se, diga que viu o interesse em {interesse} pelo {origem}. "
                f"{ask_rule} "
                "Assunto = matrícula/orientação de pós EAD. Sem preço, sem lista de cursos. "
                "Só o texto da mensagem."
            )
        else:
            system = (
                f"Você é {agent}. Escreva UMA retomada curta no WhatsApp. "
                f"Etapa={meta.get('etapa')}. Retome o ponto de MATRÍCULA/curso. "
                "NUNCA diga 'oi, sumiu?'. NUNCA mencione material, PDF, resumo, "
                "apostila ou documento que você NÃO enviou de fato. "
                "NÃO invente que mandou algo para o lead analisar. "
                "Se for retorno comercial, retome com calor SEM despejar desconto "
                "na primeira frase. Só o texto da mensagem."
            )
        user = (
            f"Nome: {nome or 'lead'}\n"
            f"Etapa: {meta.get('etapa')}\n"
            f"Trigger: {trigger}\n"
            f"Step: {job.get('step')}\n"
            f"comercial_retorno: {bool(meta.get('comercial_retorno'))}\n"
            f"Briefing: {briefing or '(vazio)'}\n"
            f"Curso/interesse: {interesse}\n"
            f"graduacao_conhecida: {graduacao or '(não informada)'}\n"
            f"Envios ativos anteriores: {enviados}\n"
            f"Lead_state: graduacao={ls.get('graduacao')} "
            f"curso={ls.get('curso_escolhido')} objecao={ls.get('objecao_ativa')}\n"
            "Nunca pergunte de novo o que já está em graduacao_conhecida."
        )
        text = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.5,
            model=getattr(settings, "briefing_model", None) or settings.openrouter_model,
        )
        out = (text or "").strip()
        # Evita repetir última mensagem ativa
        last = ""
        sends = meta.get("active_sends") or []
        if sends and isinstance(sends[-1], dict):
            last = str(sends[-1].get("text") or "")
        if out and out.casefold() != last.casefold():
            # Só esfria após série de silêncio — não em retorno comercial / vou_pensar.
            step = int(job.get("step") or 0)
            max_steps = int(job.get("max_steps") or 0)
            if (
                jtype == "retomada"
                and max_steps
                and step >= max_steps
                and "silence" in trigger
                and (meta.get("etapa") or "") != "matriculado"
            ):
                meta["etapa"] = "esfriou"
            return out
    except Exception:  # noqa: BLE001
        logger.exception("compose_active_message falhou phone=%s", phone)
    fb = _fallback()
    step = int(job.get("step") or 0)
    max_steps = int(job.get("max_steps") or 0)
    if (
        jtype == "retomada"
        and max_steps
        and step >= max_steps
        and "silence" in trigger
        and (meta.get("etapa") or "") != "matriculado"
    ):
        meta["etapa"] = "esfriou"
    return fb
