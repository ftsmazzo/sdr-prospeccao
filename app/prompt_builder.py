"""Monta o system prompt por etapa (parte fixa cacheável + variável)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.knowledge import load_conhecimento_lead, load_cursos, load_precos, load_regras

_ETAPAS_SEM_CATALOGO = frozenset({"aluno_atual", "nao_elegivel"})
_ETAPAS_COM_POS_VENDA = frozenset({"contrato_enviado", "matriculado"})

_ETAPAS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "etapas"
_POS_VENDA_PATH = Path(__file__).resolve().parent.parent / "prompts" / "pos_venda.md"

JSON_SCHEMA_HINT = """
## Formato de saída (obrigatório)
Sempre chame a ferramenta `responder` com:
{
  "reply": "texto WhatsApp ao lead",
  "state_update": {
    "nome": null,
    "graduacao": null,
    "area_interesse": null,
    "objetivo": null,
    "restricao": null,
    "decisor": null,
    "objecoes_levantadas": [],
    "objecao_ativa": null,
    "perguntou_desconto": false,
    "curso_recomendado": null,
    "curso_escolhido": null,
    "curso_alternativo": null,
    "aceite_matricula": false,
    "e_aluno_atual": false,
    "aluno_e_terceiro": false,
    "aluno_nome": null,
    "lead_irritado": false,
    "pediu_desconto_ou_condicao": false,
    "duvida_juridica": false,
    "proximo_passo": null
  },
  "action": null,
  "action_data": {},
  "offer": null
}

Regras do state_update:
- graduacao: "concluida" | "cursando" | "nao_tem" (ou omita)
- objecoes_levantadas / objecao_ativa: só categorias
  preco | tempo | validade_ead | qualidade | vou_pensar | conjuge | ja_tentei | outro
- objecao_ativa = categoria quando o lead levanta uma objeção; null quando ela foi respondida e o lead não voltou a ela
- perguntou_desconto = true SOMENTE se nesta mensagem o lead pediu desconto, abatimento ou valor menor
- pediu_desconto_ou_condicao = true SOMENTE para condição específica (corporativo, parcelamento diferente, bolsa)
- curso_escolhido = nome EXATO do catálogo (Autismo ≠ TEA – Transtorno do Espectro Autista)
- aceite_matricula = true se pediu matrícula/passo a passo/contrato com curso definido. Objetivo NÃO é requisito.
- aluno_e_terceiro = true se compra para outra pessoa; aluno_nome se souber
- NÃO envie campo "etapa" (o sistema decide)
- NÃO prometa contrato/PDF/link na reply se action for null
- NÃO diga que o contrato "não é enviado pelo WhatsApp" nem que "vai por e-mail"
- Só diga "registrei" se a action REGISTER_HANDOFF ou a oferta de encaminhamento foi executada
- Com curso escolhido e lead afirmativo: peça os dados DIRETO (sem "posso pedir agora?")
- Use EXATAMENTE carga/duração/preço dos "Fatos dos cursos"; Autismo (1000h) ≠ TEA (740h)
- Concordância de gênero pelo nome/pronomes do lead; na dúvida: "quando você quiser"
- WhatsApp: texto corrido, sem listas

offer (quando a reply TERMINA oferecendo algo que o sistema executa no próximo "sim"):
- {"type":"contrato"} | {"type":"encaminhamento","motivo":"..."} | {"type":"resumo"} | null
- Nunca ofereça o que o código não executa.
"""


def load_etapa_prompt(etapa: str) -> str:
    path = _ETAPAS_DIR / f"{etapa}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    fallback = _ETAPAS_DIR / "abertura.md"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return f"Etapa atual: {etapa}. Conduza a conversa com empatia e uma pergunta por vez."


def load_pos_venda() -> str:
    if _POS_VENDA_PATH.is_file():
        return _POS_VENDA_PATH.read_text(encoding="utf-8")
    return ""


def _identity_block(agent_name: str, agent_gender: str) -> str:
    gender = "f" if str(agent_gender).lower().startswith("f") else "m"
    if gender == "f":
        role = "consultora"
        article_role = "a consultora"
        concord = (
            "Concordância SOBRE VOCÊ: fale SEMPRE no feminino "
            '("obrigada", "fiquei feliz", "pronta", "animada", '
            f'"{article_role}"). Nunca use formas masculinas para si. '
            "Concordância COM O LEAD: use o gênero que o nome e a fala dele indicam; "
            'na dúvida, formas neutras ("quando você decidir", "quando quiser", '
            '"quando estiver pronto(a)"). '
            "Nunca aplique o seu gênero ao lead (ex.: não diga 'pronta' referindo-se a ele)."
        )
        identity = f"Você é a {agent_name}, {role} de matrícula humanizada"
    else:
        role = "consultor"
        article_role = "o consultor"
        concord = (
            "Concordância SOBRE VOCÊ: fale SEMPRE no masculino "
            '("obrigado", "fiquei feliz", "pronto", "animado", '
            f'"{article_role}"). '
            "Concordância COM O LEAD: use o gênero que o nome e a fala dele indicam; "
            'na dúvida, formas neutras ("quando você decidir", "quando quiser"). '
            "Nunca aplique o seu gênero ao lead."
        )
        identity = f"Você é o {agent_name}, {role} de matrícula humanizado"
    return (
        f"{identity} da Faveni Polo Catanduva no WhatsApp.\n"
        f"{concord}\n"
        "Objetivo: conduzir o lead até a matrícula de pós EAD "
        "(ou orientar graduação/2ª licenciatura se fizer sentido), "
        "sem alucinar e sem sair do fluxo comercial.\n"
    )


def build_system_prompt_parts(
    *,
    etapa: str,
    lead_state: dict[str, Any],
    meta_flags: dict[str, Any],
    agent_name: str = "Edu",
    agent_gender: str = "f",
    facts_block: str = "",
) -> tuple[str, str]:
    """Retorna (parte_fixa_cacheavel, parte_variavel)."""
    regras = load_regras()
    conhecimento = load_conhecimento_lead()
    etapa_txt = load_etapa_prompt(etapa)
    pos_venda = ""
    if etapa in _ETAPAS_COM_POS_VENDA:
        pv = load_pos_venda()
        if pv:
            pos_venda = f"## Pós-venda (demonstração)\n{pv}\n\n"
    catalogo = ""
    if etapa not in _ETAPAS_SEM_CATALOGO:
        catalogo = (
            "## Catálogo de cursos\n"
            f"{load_cursos()}\n\n"
            "## Tabela de valores\n"
            f"{load_precos()}\n\n"
        )
    fixed = (
        f"{_identity_block(agent_name, agent_gender)}\n"
        "## Regras de comportamento\n"
        f"{regras}\n\n"
        f"## Prompt da etapa ({etapa})\n"
        f"{etapa_txt}\n\n"
        f"{pos_venda}"
        "## Base de conhecimento (fatos para o lead)\n"
        f"{conhecimento}\n\n"
        f"{catalogo}"
        f"{JSON_SCHEMA_HINT}\n"
    )
    state_view = {
        **lead_state,
        "etapa_atual_sistema": etapa,
        "pending_contract": bool(meta_flags.get("pending_contract")),
        "contract_sent": bool(meta_flags.get("contract_sent")),
        "desconto_respondido": bool(meta_flags.get("desconto_respondido")),
        "handoff_reason": meta_flags.get("handoff_reason"),
        "handoff_avisado": bool(meta_flags.get("handoff_avisado")),
        "handoff_registrado": bool(meta_flags.get("handoff_registrado")),
        "campos_recusados": list(meta_flags.get("campos_recusados") or []),
        "matriculas": list(meta_flags.get("matriculas") or []),
    }
    variable = (
        "## Estado atual do lead (somente leitura; atualize via state_update)\n"
        f"{json.dumps(state_view, ensure_ascii=False, indent=2)}\n"
    )
    if facts_block:
        variable = f"{facts_block.strip()}\n\n{variable}"
    return fixed, variable


def build_cached_system_message(fixed: str, variable: str) -> dict[str, Any]:
    """Mensagem system com cache_control na parte fixa (Anthropic via OpenRouter)."""
    return {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": fixed,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": variable,
            },
        ],
    }


def build_system_prompt(
    *,
    etapa: str,
    lead_state: dict[str, Any],
    meta_flags: dict[str, Any],
    agent_name: str = "Edu",
    agent_gender: str = "f",
) -> str:
    """Compat: string única (fixed + variable)."""
    fixed, variable = build_system_prompt_parts(
        etapa=etapa,
        lead_state=lead_state,
        meta_flags=meta_flags,
        agent_name=agent_name,
        agent_gender=agent_gender,
    )
    return f"{fixed}\n{variable}"
