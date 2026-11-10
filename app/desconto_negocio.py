"""Negociação de desconto à vista (demo / métrica do cliente).

Escada padrão (quando DEMO_NEGOCIO_DESCONTO=true):
  1ª pedida → 10% (tabela)
  2ª pedida → alvo (padrão 20%)
  3ª pedida → teto (padrão 30%)
  além disso → handoff desconto_insistencia

Sem a flag, só a tabela (10%) e a 2ª pedida vai a handoff (comportamento antigo).
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.pricing import PriceBand, price_for_course


def _parse_brl(raw: str) -> float:
    return float((raw or "0").replace(".", "").replace(",", "."))


def _format_brl(value: float) -> str:
    cents = int(round(value * 100))
    reais, c = divmod(cents, 100)
    s = f"{reais:,}".replace(",", ".")
    return f"{s},{c:02d}"


def a_vista_com_percentual(band: PriceBand, pct: int) -> str:
    """Aplica % sobre o total em 18x (base da tabela)."""
    total = _parse_brl(band.total_18)
    pct = max(0, min(90, int(pct)))
    return _format_brl(total * (100 - pct) / 100.0)


def ladder_pcts(settings: Settings | None = None) -> list[int]:
    s = settings or get_settings()
    tabela = int(getattr(s, "desconto_tabela_avista_pct", 10) or 10)
    if not getattr(s, "demo_negocio_desconto", False):
        return [tabela]
    alvo = int(getattr(s, "desconto_negocio_alvo_pct", 20) or 20)
    teto = int(getattr(s, "desconto_negocio_max_pct", 30) or 30)
    out: list[int] = []
    for p in (tabela, alvo, teto):
        if p not in out:
            out.append(p)
    return out


def next_desconto_pct(meta: dict[str, Any], settings: Settings | None = None) -> int | None:
    """Próximo % a oferecer nesta pedida, ou None → handoff."""
    ladder = ladder_pcts(settings)
    nivel = int(meta.get("desconto_negociacao_nivel") or 0)
    if nivel >= len(ladder):
        return None
    return ladder[nivel]


def register_desconto_offer(meta: dict[str, Any], pct: int) -> None:
    nivel = int(meta.get("desconto_negociacao_nivel") or 0)
    meta["desconto_negociacao_nivel"] = nivel + 1
    meta["desconto_oferta_atual_pct"] = int(pct)
    meta["desconto_respondido"] = True
    ofertas = list(meta.get("desconto_ofertas") or [])
    ofertas.append(int(pct))
    meta["desconto_ofertas"] = ofertas


def label_avista_para_curso(course: str | None, pct: int) -> str | None:
    band = price_for_course(course)
    if not band:
        return None
    return f"R$ {a_vista_com_percentual(band, pct)}"


def negociacao_block_for_prompt(meta: dict[str, Any], ls: dict[str, Any]) -> str:
    """Texto variável no system prompt sobre a escada de desconto."""
    s = get_settings()
    if not getattr(s, "demo_negocio_desconto", False):
        return (
            "Desconto: só a condição à vista da tabela (10% no total). "
            "Se o lead insistir em outro desconto após você já ter apresentado a tabela → "
            "o sistema encaminha a especialista (não invente %)."
        )
    ladder = ladder_pcts(s)
    nivel = int(meta.get("desconto_negociacao_nivel") or 0)
    curso = ls.get("curso_escolhido") or ls.get("curso_recomendado")
    atual = meta.get("desconto_oferta_atual_pct")
    lines = [
        "## Negociação comercial (demo — liberdade com limites)",
        f"Escada à vista sobre o total: {' → '.join(str(p) + '%' for p in ladder)}.",
        f"Nível já oferecido: {nivel}/{len(ladder)}."
        + (f" Última oferta: {atual}%." if atual else ""),
    ]
    nxt = next_desconto_pct(meta, s)
    if nxt is None:
        lines.append(
            "Teto atingido: NÃO invente desconto maior. Ofereça registrar com especialista "
            "(offer encaminhamento) ou confirme se prefere a última condição."
        )
    else:
        valor = label_avista_para_curso(str(curso) if curso else None, nxt)
        lines.append(
            f"Nesta pedida de desconto, ofereça **{nxt}% à vista**"
            + (f" (= {valor} no curso atual)" if valor else "")
            + ". Deixe claro que é condição especial do polo para fechar à vista, "
            "sem inventar mensalidade menor nem bolsa."
        )
    if meta.get("comercial_retorno"):
        lines.append(
            "Retorno pós-handoff: NÃO despeje o desconto na primeira frase. "
            "Retome com calor, confirme se ainda faz sentido o curso; "
            "só na conversa, se o lead voltar ao preço/desconto, use a escada acima."
        )
    return "\n".join(lines)


def exit_handoff_to_negociacao(meta: dict[str, Any]) -> str:
    """Sai do handoff para retomar venda com gordura de desconto.

    Só opera em `handoff_humano`. Recusa etapas terminais (matriculado/fechamento…).
    """
    etapa = meta.get("etapa") or ""
    if etapa in ("matriculado", "fechamento", "aluno_atual", "nao_elegivel"):
        raise ValueError(f"etapa_protegida:{etapa}")
    if etapa != "handoff_humano":
        raise ValueError(f"nao_em_handoff:{etapa or 'vazia'}")
    prev = meta.get("etapa_antes_handoff") or "objecao"
    if prev in (
        "handoff_humano",
        "esfriou",
        "matriculado",
        "fechamento",
        "aluno_atual",
        "nao_elegivel",
    ):
        prev = "objecao"
    meta["etapa"] = prev
    meta.pop("handoff_reason", None)
    meta.pop("handoff_request_id", None)
    meta["handoff_avisado"] = False
    meta["handoff_registrado"] = False
    meta["comercial_retorno"] = True
    meta["retomadas_paused"] = False
    # Já passou pela tabela (10%); próxima pedida sobe na escada.
    if int(meta.get("desconto_negociacao_nivel") or 0) < 1:
        meta["desconto_negociacao_nivel"] = 1
        meta["desconto_respondido"] = True
        meta["desconto_oferta_atual_pct"] = 10
    ls = meta.get("lead_state") if isinstance(meta.get("lead_state"), dict) else {}
    if ls:
        ls["objecao_ativa"] = "preco"
        ls["aceite_matricula"] = False
        ls["pediu_desconto_ou_condicao"] = False
        ls["duvida_juridica"] = False
        ls["lead_irritado"] = False
        meta["lead_state"] = ls
    meta["objecoes_sem_avanco"] = 0
    return prev


def all_negociated_avista_tokens(settings: Settings | None = None) -> set[str]:
    """Valores à vista da escada (sem R$) para o fiscal de preço."""
    from app.pricing import _ALL_BANDS

    s = settings or get_settings()
    pcts = ladder_pcts(s)
    out: set[str] = set()
    for band in _ALL_BANDS:
        for pct in pcts:
            out.add(a_vista_com_percentual(band, pct))
    return out
