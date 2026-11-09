"""Smoke permanente da máquina de etapas (Fase 2 + correções). Reusado na Fase 5."""

from __future__ import annotations

from app.lead_state import (
    advance_etapa,
    can_run_action,
    ensure_lead_state,
    merge_state_update,
    reply_looks_like_promise,
    rewrite_blocked_action_reply,
)
from app.prompt_builder import build_system_prompt
from app.schemas import looks_like_json, normalize_cpf, parse_agent_response, safe_fallback_response


def _base_recomendacao() -> dict:
    meta: dict = {}
    ensure_lead_state(meta)
    ls = meta["lead_state"]
    merge_state_update(
        ls,
        {
            "graduacao": "concluida",
            "area_interesse": "pedagogia",
            "objetivo": "carreira",
            "curso_escolhido": "Neuropsicopedagogia",
        },
    )
    advance_etapa(meta)
    assert meta["etapa"] == "recomendacao", meta["etapa"]
    return meta


def test_parse_and_cpf():
    r = parse_agent_response(
        '{"reply":"Oi","state_update":{"graduacao":"concluida"},"action":null,"action_data":{}}'
    )
    assert r and r.reply == "Oi"
    r2 = parse_agent_response('```json\n{"reply":"Ok","state_update":{},"action":null}\n```')
    assert r2 and r2.reply == "Ok"
    fb = safe_fallback_response("{not json")
    assert not looks_like_json(fb.reply)
    assert normalize_cpf("123.456.789-01") == "12345678901"
    assert normalize_cpf("123") is None


def test_primeiro_desconto_nao_e_handoff():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"perguntou_desconto": True})
    advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    assert ls["objecao_ativa"] == "preco"
    assert "preco" in ls["objecoes_levantadas"]
    assert meta["desconto_respondido"] is True
    assert meta.get("handoff_reason") is None


def test_segundo_desconto_e_handoff():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"perguntou_desconto": True})
    advance_etapa(meta)
    assert meta["desconto_respondido"] is True
    # turno seguinte: insiste
    merge_state_update(ls, {"perguntou_desconto": True})
    advance_etapa(meta)
    assert meta["etapa"] == "handoff_humano"
    assert meta["handoff_reason"] == "desconto_insistencia"


def test_achei_caro_depois_desconto_primeira_vez():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"objecao_ativa": "preco", "objecoes_levantadas": ["preco"]})
    advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    assert meta.get("desconto_respondido") is False
    # primeira pergunta de desconto após "achei caro"
    merge_state_update(ls, {"perguntou_desconto": True, "objecao_ativa": "preco"})
    advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    assert meta["desconto_respondido"] is True
    assert meta.get("handoff_reason") is None


def test_mesma_objecao_varios_turnos_sem_handoff():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"objecao_ativa": "preco", "objecoes_levantadas": ["preco"]})
    advance_etapa(meta)
    count_after_first = meta.get("objecoes_sem_avanco", 0)
    for _ in range(4):
        merge_state_update(ls, {"objecao_ativa": "preco"})
        advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    assert meta.get("objecoes_sem_avanco", 0) == count_after_first
    assert meta["etapa"] != "handoff_humano"


def test_objecao_no_fechamento_zera_aceite():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"aceite_matricula": True, "objecao_ativa": None})
    advance_etapa(meta)
    assert meta["etapa"] == "fechamento"
    merge_state_update(ls, {"objecao_ativa": "tempo", "objecoes_levantadas": ["tempo"]})
    advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    assert ls["aceite_matricula"] is False
    # sem reconfirmação não volta
    merge_state_update(ls, {"objecao_ativa": None})
    advance_etapa(meta)
    assert meta["etapa"] == "recomendacao"
    # reconfirma
    merge_state_update(ls, {"aceite_matricula": True, "objecao_ativa": None})
    advance_etapa(meta)
    assert meta["etapa"] == "fechamento"


def test_objecao_resolvida_volta_recomendacao():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"objecao_ativa": "validade_ead", "objecoes_levantadas": ["validade_ead"]})
    advance_etapa(meta)
    assert meta["etapa"] == "objecao"
    merge_state_update(ls, {"objecao_ativa": None})
    advance_etapa(meta)
    assert meta["etapa"] == "recomendacao"


def test_action_bloqueada_e_promessa_sem_acao():
    meta = {
        "etapa": "recomendacao",
        "lead_state": {
            "curso_escolhido": None,
            "aceite_matricula": False,
            "graduacao": "concluida",
            "objecoes_levantadas": [],
            "objecao_ativa": None,
        },
    }
    ok, reason = can_run_action(meta, "FOLLOWUP_DOC")
    assert not ok
    promised = "Vou preparar seu contrato agora e te mando o PDF."
    assert reply_looks_like_promise(promised)
    rewritten = rewrite_blocked_action_reply(reason, promised, meta["lead_state"])
    assert "pdf" not in rewritten.lower()
    assert "http" not in rewritten.lower()
    assert "confirma qual curso" in rewritten.lower()

    # promessa sem action
    r2 = rewrite_blocked_action_reply("promessa_sem_acao", promised, meta["lead_state"])
    assert "confirma qual curso" in r2.lower()


def test_promessa_somente_entrega_nao_mencao():
    nao = [
        "Quer seguir com a matrícula?",
        "Pra matrícula você vai precisar do RG e do diploma",
        "O contrato é simples, posso te explicar?",
        "O link de pagamento vem depois da confirmação.",
        "Documento complementar pode ser enviado depois.",
    ]
    for msg in nao:
        assert not reply_looks_like_promise(msg), msg

    sim = [
        "Vou preparar seu contrato agora",
        "Já te mando o link",
        "Preparei sua matrícula",
        "Em alguns minutos te envio o PDF",
        "Segue o link da matrícula demonstração",
        "Aqui está o contrato para você olhar",
    ]
    for msg in sim:
        assert reply_looks_like_promise(msg), msg


def test_prompt_builder_inclui_schema():
    p = build_system_prompt(
        etapa="abertura",
        lead_state=ensure_lead_state({}),
        meta_flags={},
        agent_name="Ana",
        agent_gender="f",
    )
    assert "perguntou_desconto" in p
    assert "objecao_ativa" in p
    assert "Você é a Ana, consultora" in p
    assert "obrigada" in p
    assert "Você é o Edu, consultor" not in p


def test_catalogo_cursos_por_etapa():
    ls = ensure_lead_state({})
    marker = "Neuropsicopedagogia Institucional e Clínica"
    com_catalogo = (
        "abertura",
        "qualificacao",
        "recomendacao",
        "objecao",
        "fechamento",
        "contrato_enviado",
        "handoff_humano",
    )
    sem_catalogo = ("aluno_atual", "nao_elegivel")
    for etapa in com_catalogo:
        p = build_system_prompt(etapa=etapa, lead_state=ls, meta_flags={})
        assert marker in p, etapa
        assert "## Catálogo de cursos" in p, etapa
    for etapa in sem_catalogo:
        p = build_system_prompt(etapa=etapa, lead_state=ls, meta_flags={})
        assert marker not in p, etapa
        assert "## Catálogo de cursos" not in p, etapa


def test_saida_handoff_condicao_especial_com_aceite():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    antes = meta["etapa"]
    merge_state_update(ls, {"pediu_desconto_ou_condicao": True})
    advance_etapa(meta)
    assert meta["etapa"] == "handoff_humano"
    assert meta["handoff_reason"] == "condicao_especial"
    assert meta.get("etapa_antes_handoff") == antes
    assert ls["pediu_desconto_ou_condicao"] is False
    # turno seguinte: modelo só manda curso + aceite (sem reenviar flag false)
    merge_state_update(ls, {"curso_escolhido": "Neuropsicopedagogia", "aceite_matricula": True})
    advance_etapa(meta)
    assert meta["etapa"] == "fechamento"
    assert meta.get("handoff_reason") is None


def test_handoff_irritado_sem_aceite_continua():
    meta = _base_recomendacao()
    ls = meta["lead_state"]
    merge_state_update(ls, {"lead_irritado": True})
    advance_etapa(meta)
    assert meta["etapa"] == "handoff_humano"
    assert meta["handoff_reason"] == "lead_irritado"
    etapa_antes = meta.get("etapa_antes_handoff")
    # turno seguinte sem flags e sem aceite
    merge_state_update(ls, {"aceite_matricula": False, "objecao_ativa": None})
    advance_etapa(meta)
    assert meta["etapa"] == "handoff_humano"
    assert meta.get("etapa_antes_handoff") == etapa_antes


if __name__ == "__main__":
    test_parse_and_cpf()
    test_primeiro_desconto_nao_e_handoff()
    test_segundo_desconto_e_handoff()
    test_achei_caro_depois_desconto_primeira_vez()
    test_mesma_objecao_varios_turnos_sem_handoff()
    test_objecao_no_fechamento_zera_aceite()
    test_objecao_resolvida_volta_recomendacao()
    test_action_bloqueada_e_promessa_sem_acao()
    test_prompt_builder_inclui_schema()
    test_saida_handoff_condicao_especial_com_aceite()
    test_handoff_irritado_sem_aceite_continua()
    print("ALL_OK")
