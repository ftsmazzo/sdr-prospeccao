"""Testes do fiscal automático da simulação."""

from __future__ import annotations

from scripts.sim.auto_judge import judge_agent_reply, load_catalog, looks_like_farewell


def test_catalog_loads():
    cat = load_catalog()
    assert any("Enfermagem em Estética" in n for n, _ in cat)
    assert any(h >= 1000 for _, h in cat)


def test_mais_de_uma_pergunta_na_resposta_inteira():
    reply = "Legal! Você já se formou?\nE qual área te interessa?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "mais_de_uma_pergunta" for x in v)


def test_uma_pergunta_ok():
    reply = "Saúde, que legal! Você já trabalha na área?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert not any(x["regra"] == "mais_de_uma_pergunta" for x in v)


def test_sem_pergunta():
    reply = "Tranquilo, faz sentido."
    v = judge_agent_reply(reply, turno=2, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "sem_pergunta_nem_proximo_passo" for x in v)


def test_despedida_sem_pergunta_ok():
    reply = "Quando quiser retomar, é só me chamar aqui."
    lead = "Por enquanto é só, obrigada. Vou pensar e te aviso. Até mais!"
    assert looks_like_farewell(lead)
    v = judge_agent_reply(
        reply,
        turno=8,
        aceite_matricula=False,
        action_executed=False,
        lead_text=lead,
    )
    assert not any(x["regra"] == "sem_pergunta_nem_proximo_passo" for x in v)
    assert not looks_like_farewell(
        "Por enquanto vou focar na pós em Enfermagem em Estética mesmo."
    )
    assert looks_like_farewell("Quero pensar mais um pouco. Depois te falo, tá?")
    assert looks_like_farewell(
        "Entrarei em contato caso decida seguir. Tenha um ótimo dia!"
    )
    assert looks_like_farewell("Obrigada pela atenção. Continuarei avaliando.")


def test_promessa_lembrete_fiscal():
    reply = "Vou te chamar em alguns dias para acompanhar sua decisão."
    v = judge_agent_reply(reply, turno=9, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "promessa_sem_acao" for x in v)


def test_preco_fora_tabela():
    reply = "Temos por R$ 49,90. Quer seguir?"
    v = judge_agent_reply(reply, turno=3, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "preco_fora_tabela" for x in v)


def test_precos_tabela_ok():
    for price in ("R$ 69,90", "R$ 79,90", "R$ 89,90", "R$ 1.294,38"):
        reply = f"A mensalidade é {price}. Quer seguir?"
        v = judge_agent_reply(reply, turno=3, aceite_matricula=False, action_executed=False)
        assert not any(x["regra"] == "preco_fora_tabela" for x in v), price


def test_cpf_antes_aceite():
    reply = "Me manda nome completo, CPF e data de nascimento?"
    v = judge_agent_reply(reply, turno=4, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "cpf_antes_de_aceite" for x in v)


def test_mencionar_cpf_sem_pedir_nao_viola():
    reply = (
        "Na matrícula você envia diploma e o CPF entra no contrato. "
        "Qual área te interessa?"
    )
    v = judge_agent_reply(reply, turno=4, aceite_matricula=False, action_executed=False)
    assert not any(x["regra"] == "cpf_antes_de_aceite" for x in v)


def test_curso_uti_fora_catalogo():
    reply = "Temos pós em UTI sim. Quer saber mais?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "curso_fora_catalogo" for x in v)


def test_todos_cursos_catalogo_ok():
    cat = load_catalog()
    assert len(cat) >= 26
    for name, hours in cat:
        reply = f"A pós em {name} tem {hours}h. Quer seguir?"
        v = judge_agent_reply(reply, turno=2, aceite_matricula=False, action_executed=False)
        assert not any(x["regra"] == "curso_fora_catalogo" for x in v), name


def test_tea_e_psicopedagogia_no_catalogo():
    for reply in (
        "A pós em Psicopedagogia Institucional e Clínica tem 620h.",
        "Psicopedagogia é uma área muito interessante. Quer saber a mensalidade?",
        "Temos TEA – Transtorno do Espectro Autista (740h).",
        "A especialização em TEA - Transtorno do Espectro Autista é 740h.",
        "TEA tem carga horária de 740h e a mensalidade é R$ 79,90.",
    ):
        v = judge_agent_reply(reply, turno=2, aceite_matricula=False, action_executed=False)
        assert not any(x["regra"] == "curso_fora_catalogo" for x in v), reply


def test_curso_uti_negado_pelo_lead_nao_viola():
    lead = "Quero pós em UTI, vocês têm?"
    reply = (
        "A pós em UTI não está no catálogo oficial do polo. "
        "Se quiser, posso te apresentar outras opções na área da saúde. Quer que eu faça isso?"
    )
    v = judge_agent_reply(
        reply,
        turno=3,
        aceite_matricula=False,
        action_executed=False,
        lead_text=lead,
    )
    assert not any(x["regra"] == "curso_fora_catalogo" for x in v)


def test_area_generica_nao_e_curso():
    reply = "Quer que eu te mostre as opções de pós em saúde para você já ir se planejando?"
    v = judge_agent_reply(reply, turno=5, aceite_matricula=False, action_executed=False)
    assert not any(x["regra"] == "curso_fora_catalogo" for x in v)
    reply2 = "Temos especialização em enfermagem na área; quer que eu te diga o nome exato do catálogo?"
    v2 = judge_agent_reply(reply2, turno=6, aceite_matricula=False, action_executed=False)
    assert not any(x["regra"] == "curso_fora_catalogo" for x in v2)


def test_tag_audio():
    reply = "[chuckles] Olha, faz sentido. Quer seguir?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "tag_audio_no_texto" for x in v)
