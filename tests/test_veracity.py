"""Detectores de veracidade / ação fingida / preço / aceite."""

from __future__ import annotations

from app.veracity import (
    apply_enrollment_intent,
    claims_unbacked_action,
    lead_requests_enrollment,
    reply_has_disallowed_price,
    reply_offers_enrollment,
)


def test_recebi_rg_sem_midia():
    assert (
        claims_unbacked_action("Recebi seu RG, Paulo!", has_media=False)
        == "recebeu_sem_midia"
    )
    assert (
        claims_unbacked_action("Recebi seu RG, Paulo!", has_media=True) is None
    )


def test_confirmei_com_polo():
    assert (
        claims_unbacked_action("Confirmei com o polo e não temos UTI.")
        == "confirmacao_polo"
    )


def test_handoff_reforcar():
    assert (
        claims_unbacked_action(
            "Vou reforçar com o especialista do polo.",
            just_entered_handoff=False,
            handoff_avisado=False,
        )
        == "handoff_sem_acao"
    )
    assert (
        claims_unbacked_action(
            "Vou pedir pra um especialista te ajudar.",
            just_entered_handoff=True,
            handoff_avisado=False,
        )
        is None
    )
    assert (
        claims_unbacked_action(
            "Vou reforçar com o especialista.",
            just_entered_handoff=True,
            handoff_avisado=True,
        )
        == "handoff_repetido"
    )


def test_preco_81_fora_tabela():
    assert reply_has_disallowed_price(
        "à vista tem 10%, ficando R$ 81,00 por mês em média"
    )
    assert not reply_has_disallowed_price("mensalidade R$ 89,90 e à vista R$ 1.456,38")


def test_enrollment_intent():
    assert lead_requests_enrollment("Manda o passo a passo da matrícula agora")
    ls: dict = {"curso_escolhido": "IA para Negócios", "aceite_matricula": False}
    apply_enrollment_intent(ls, "Quero me matricular")
    assert ls["aceite_matricula"] is True


def test_offers_enrollment():
    assert reply_offers_enrollment("Quer que eu te envie as condições para matrícula?")
