"""Monta o system prompt por etapa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.knowledge import load_conhecimento_lead, load_regras

_ETAPAS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "etapas"

JSON_SCHEMA_HINT = """
## Formato de saída (obrigatório)
Responda APENAS com um JSON válido (sem markdown, sem texto fora do JSON):
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
    "lead_irritado": false,
    "pediu_desconto_ou_condicao": false,
    "duvida_juridica": false,
    "proximo_passo": null
  },
  "action": null,
  "action_data": {}
}

Regras do state_update:
- graduacao: "concluida" | "cursando" | "nao_tem" (ou omita)
- objecoes_levantadas / objecao_ativa: só categorias
  preco | tempo | validade_ead | qualidade | vou_pensar | conjuge | ja_tentei | outro
- objecao_ativa = categoria quando o lead levanta uma objeção; null quando ela foi respondida e o lead não voltou a ela
- perguntou_desconto = true SOMENTE se nesta mensagem o lead pediu desconto, abatimento ou valor menor
  ("achei caro" sem pedir desconto = só objecao_ativa preco, perguntou_desconto false)
- pediu_desconto_ou_condicao = true SOMENTE para condição específica (corporativo, parcelamento diferente, bolsa)
- curso_recomendado = o que VOCÊ sugeriu; curso_escolhido = só o que o LEAD escolheu
- aceite_matricula = true SOMENTE se o lead disse explicitamente que quer seguir com a matrícula daquele curso
- e_aluno_atual = true SOMENTE se o lead diz que já é aluno / problema em curso em andamento (boleto de matrícula nova NÃO conta)
- NÃO envie campo "etapa" (o sistema decide)
- NÃO prometa contrato, PDF ou link na reply se action for null

Actions (só quando permitido pelo fluxo):
- LEAD_DATA: action_data { "full_name", "cpf", "birth_date" }
- FOLLOWUP_DOC: action_data { "course", "full_name", "cpf", "birth_date" } — agenda contrato/PDF
- CHECKOUT_READY: action_data { "course" } — só se não houver contrato pendente
- Na maioria dos turnos: action = null
"""


def load_etapa_prompt(etapa: str) -> str:
    path = _ETAPAS_DIR / f"{etapa}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    fallback = _ETAPAS_DIR / "abertura.md"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return f"Etapa atual: {etapa}. Conduza a conversa com empatia e uma pergunta por vez."


def build_system_prompt(*, etapa: str, lead_state: dict[str, Any], meta_flags: dict[str, Any]) -> str:
    regras = load_regras()
    conhecimento = load_conhecimento_lead()
    etapa_txt = load_etapa_prompt(etapa)
    state_view = {
        **lead_state,
        "etapa_atual_sistema": etapa,
        "pending_contract": bool(meta_flags.get("pending_contract")),
        "contract_sent": bool(meta_flags.get("contract_sent")),
        "desconto_respondido": bool(meta_flags.get("desconto_respondido")),
        "handoff_reason": meta_flags.get("handoff_reason"),
    }
    return (
        "Você é o Edu, consultor de matrícula humanizado da Faveni Polo Catanduva no WhatsApp.\n"
        "Objetivo: conduzir o lead até a matrícula de pós EAD (ou orientar graduação/2ª licenciatura se fizer sentido), "
        "sem alucinar e sem sair do fluxo comercial.\n\n"
        "## Regras de comportamento\n"
        f"{regras}\n\n"
        f"## Prompt da etapa ({etapa})\n"
        f"{etapa_txt}\n\n"
        "## Base de conhecimento (fatos para o lead)\n"
        f"{conhecimento}\n\n"
        "## Estado atual do lead (somente leitura; atualize via state_update)\n"
        f"{json.dumps(state_view, ensure_ascii=False, indent=2)}\n"
        f"{JSON_SCHEMA_HINT}\n"
    )
