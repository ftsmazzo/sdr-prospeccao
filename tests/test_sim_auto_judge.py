"""Testes do fiscal automático da simulação."""

from __future__ import annotations

from scripts.sim.auto_judge import judge_agent_reply, load_catalog


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


def test_preco_errado():
    reply = "Temos por R$ 49,90. Quer seguir?"
    v = judge_agent_reply(reply, turno=3, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "preco_diferente_69_90" for x in v)


def test_cpf_antes_aceite():
    reply = "Me manda nome completo, CPF e data de nascimento?"
    v = judge_agent_reply(reply, turno=4, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "cpf_antes_de_aceite" for x in v)


def test_curso_uti_fora_catalogo():
    reply = "Temos pós em UTI sim. Quer saber mais?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "curso_fora_catalogo" for x in v)


def test_tag_audio():
    reply = "[chuckles] Olha, faz sentido. Quer seguir?"
    v = judge_agent_reply(reply, turno=1, aceite_matricula=False, action_executed=False)
    assert any(x["regra"] == "tag_audio_no_texto" for x in v)
