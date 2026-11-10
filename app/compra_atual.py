"""Compra em andamento (separada de matriculas[] concluídas)."""

from __future__ import annotations

from typing import Any


def default_compra_atual() -> dict[str, Any]:
    return {
        "active": True,
        "aluno_nome": None,
        "aluno_e_terceiro": False,
        "aluno_relacao": None,
        "aluno_genero": None,
        "graduacao_aluno": None,
        "interesse_aluno": None,
        "curso_recomendado": None,
        "curso_escolhido": None,
        "curso_alternativo": None,
        # Dados pessoais do ALUNO desta compra (não misturar com matrícula anterior).
        "aluno_dados": {"nome": None, "cpf": None, "birth_date": None},
        "aceite": False,
        "etapa": "qualificacao",
    }


def ensure_compra_atual(meta: dict[str, Any]) -> dict[str, Any]:
    ca = meta.get("compra_atual")
    if isinstance(ca, dict) and ca.get("active", True):
        base = default_compra_atual()
        for k in base:
            if k == "aluno_dados":
                prev = ca.get("aluno_dados") if isinstance(ca.get("aluno_dados"), dict) else {}
                merged = dict(base["aluno_dados"])
                merged.update({kk: prev.get(kk, merged[kk]) for kk in merged})
                base["aluno_dados"] = merged
            else:
                base[k] = ca.get(k, base[k])
        meta["compra_atual"] = base
        return base
    ca = default_compra_atual()
    meta["compra_atual"] = ca
    return ca


def sync_ls_into_compra_atual(ls: dict[str, Any], ca: dict[str, Any]) -> None:
    """Copia campos da compra ativa do lead_state → compra_atual."""
    if ls.get("aluno_e_terceiro") is not None:
        ca["aluno_e_terceiro"] = bool(ls.get("aluno_e_terceiro"))
    for src, dst in (
        ("aluno_nome", "aluno_nome"),
        ("aluno_relacao", "aluno_relacao"),
        ("aluno_genero", "aluno_genero"),
        ("graduacao", "graduacao_aluno"),
        ("area_interesse", "interesse_aluno"),
        ("curso_recomendado", "curso_recomendado"),
        ("curso_escolhido", "curso_escolhido"),
        ("curso_alternativo", "curso_alternativo"),
    ):
        val = ls.get(src)
        if val is not None and val != "":
            ca[dst] = val
    if ls.get("aceite_matricula"):
        ca["aceite"] = True


def apply_compra_atual_to_ls(ls: dict[str, Any], ca: dict[str, Any]) -> None:
    """Espelha compra_atual → lead_state (para advance_etapa / prompts)."""
    ls["aluno_e_terceiro"] = bool(ca.get("aluno_e_terceiro"))
    ls["aluno_nome"] = ca.get("aluno_nome")
    ls["aluno_relacao"] = ca.get("aluno_relacao")
    ls["aluno_genero"] = ca.get("aluno_genero")
    if ca.get("graduacao_aluno") is not None:
        ls["graduacao"] = ca.get("graduacao_aluno")
    if ca.get("interesse_aluno") is not None:
        ls["area_interesse"] = ca.get("interesse_aluno")
    if ca.get("curso_recomendado") is not None:
        ls["curso_recomendado"] = ca.get("curso_recomendado")
    if ca.get("curso_escolhido") is not None:
        ls["curso_escolhido"] = ca.get("curso_escolhido")
    if ca.get("curso_alternativo") is not None:
        ls["curso_alternativo"] = ca.get("curso_alternativo")
    ls["aceite_matricula"] = bool(ca.get("aceite"))


def format_compra_atual_block(ca: dict[str, Any] | None) -> str:
    if not isinstance(ca, dict) or not ca.get("active", True):
        return "Compra em andamento: nenhuma."
    parts: list[str] = []
    if ca.get("aluno_e_terceiro"):
        rel = ca.get("aluno_relacao") or "outra pessoa"
        nome = ca.get("aluno_nome")
        parts.append(f"para {rel}" + (f" ({nome})" if nome else ""))
    else:
        parts.append("para o próprio lead")
    if ca.get("graduacao_aluno"):
        parts.append(f"graduação={ca['graduacao_aluno']}")
    if ca.get("interesse_aluno"):
        parts.append(f"interesse={ca['interesse_aluno']}")
    if ca.get("curso_recomendado"):
        parts.append(f"recomendado={ca['curso_recomendado']}")
    if ca.get("curso_escolhido"):
        parts.append(f"escolhido={ca['curso_escolhido']}")
    if ca.get("aceite"):
        parts.append("aceite=sim")
    dados = ca.get("aluno_dados") if isinstance(ca.get("aluno_dados"), dict) else {}
    if dados.get("nome") or dados.get("cpf") or dados.get("birth_date"):
        bits = []
        if dados.get("nome"):
            bits.append(f"nome={dados['nome']}")
        if dados.get("cpf"):
            bits.append("cpf=ok")
        if dados.get("birth_date"):
            bits.append("nasc=ok")
        parts.append("aluno_dados(" + ", ".join(bits) + ")")
    if ca.get("etapa"):
        parts.append(f"etapa_compra={ca['etapa']}")
    return "Compra em andamento: " + "; ".join(parts) + "."


def format_matriculas_block(matriculas: list[Any] | None) -> str:
    items = [m for m in (matriculas or []) if isinstance(m, dict) and m.get("curso")]
    if not items:
        return "Matrículas já feitas: nenhuma."
    bits = []
    for m in items:
        nome = m.get("aluno_nome") or "?"
        status = m.get("status") or "confirmada"
        bits.append(f"{m['curso']} ({nome}, {status})")
    return "Matrículas já feitas: " + "; ".join(bits) + "."
