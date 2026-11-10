"""Resolve quem é o aluno do contrato vs o comprador (dono da conversa)."""

from __future__ import annotations

from typing import Any

from app.compra_atual import ensure_compra_atual


def _aluno_dados(meta: dict[str, Any]) -> dict[str, Any]:
    ca = meta.get("compra_atual") if isinstance(meta.get("compra_atual"), dict) else {}
    dados = ca.get("aluno_dados") if isinstance(ca.get("aluno_dados"), dict) else {}
    return dict(dados or {})


def is_third_person_purchase(meta: dict[str, Any], ls: dict[str, Any] | None = None) -> bool:
    ls = ls or meta.get("lead_state") or {}
    ca = meta.get("compra_atual") if isinstance(meta.get("compra_atual"), dict) else {}
    return bool(ls.get("aluno_e_terceiro") or ca.get("aluno_e_terceiro"))


def resolve_contract_party(
    meta: dict[str, Any],
    ls: dict[str, Any] | None = None,
    *,
    push_name: str = "",
) -> dict[str, str]:
    """Retorna nomes/dados do ALUNO (contrato) e do COMPRADOR (conversa)."""
    ls = ls or meta.get("lead_state") or {}
    ca = ensure_compra_atual(meta)
    dados = _aluno_dados(meta)
    third = is_third_person_purchase(meta, ls)

    comprador = str(
        ls.get("nome") or meta.get("comprador_nome") or push_name or ""
    ).strip()
    # full_name do meta só é do comprador se NÃO for compra para terceiro
    # (legado: full_name podia ser sobrescrito — prioriza ls.nome).
    if not third and not comprador:
        comprador = str(meta.get("full_name") or "").strip()

    if third:
        aluno = str(
            dados.get("nome")
            or ls.get("aluno_nome")
            or ca.get("aluno_nome")
            or ""
        ).strip()
        cpf = str(dados.get("cpf") or meta.get("aluno_cpf") or "").strip()
        birth = str(
            dados.get("birth_date") or meta.get("aluno_birth_date") or ""
        ).strip()
    else:
        aluno = str(
            meta.get("full_name") or ls.get("nome") or push_name or ""
        ).strip()
        cpf = str(meta.get("cpf") or dados.get("cpf") or "").strip()
        birth = str(meta.get("birth_date") or dados.get("birth_date") or "").strip()
        if not comprador:
            comprador = aluno

    return {
        "aluno_nome": aluno,
        "comprador_nome": comprador,
        "cpf": cpf,
        "birth_date": birth,
        "third": "1" if third else "0",
    }


def store_aluno_dados(
    meta: dict[str, Any],
    ls: dict[str, Any],
    *,
    nome: str | None = None,
    cpf: str | None = None,
    birth_date: str | None = None,
) -> None:
    """Grava dados do aluno na compra_atual sem apagar matrícula anterior."""
    ca = ensure_compra_atual(meta)
    dados = dict(ca.get("aluno_dados") or {})
    if nome:
        dados["nome"] = nome
        ls["aluno_nome"] = nome
        ca["aluno_nome"] = nome
    if cpf:
        dados["cpf"] = cpf
    if birth_date:
        dados["birth_date"] = birth_date
    ca["aluno_dados"] = dados
    meta["compra_atual"] = ca
    meta["lead_state"] = ls


def missing_party_fields(meta: dict[str, Any], ls: dict[str, Any]) -> list[str]:
    party = resolve_contract_party(meta, ls)
    missing: list[str] = []
    if not party["aluno_nome"]:
        missing.append("nome completo")
    if not party["cpf"]:
        missing.append("CPF")
    if not party["birth_date"]:
        missing.append("data de nascimento")
    return missing
