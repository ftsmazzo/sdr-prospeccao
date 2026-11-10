import logging
import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("edu.knowledge")

_FORBIDDEN = (
    "98819-6906",
    "nota máxima no mec",
)


def _resolve(path_str: str, *fallbacks: Path) -> Path | None:
    path = Path(path_str)
    if path.is_file():
        return path
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / path_str, *fallbacks):
        if candidate.is_file():
            return candidate
    return None


def _sanitize_for_model(text: str, label: str) -> str:
    low = text.lower()
    for bad in _FORBIDDEN:
        if bad in low:
            logger.error("conteúdo proibido em %s: %r — removendo ocorrências", label, bad)
            text = re.sub(re.escape(bad), "[omitido]", text, flags=re.IGNORECASE)
            # também remover variações com espaços no telefone
            text = re.sub(r"\(17\)\s*98819-6906", "[omitido]", text, flags=re.IGNORECASE)
            text = re.sub(r"17\s*98819-6906", "[omitido]", text, flags=re.IGNORECASE)
    return text


@lru_cache
def load_regras() -> str:
    settings = get_settings()
    path = _resolve(
        settings.regras_path,
        Path(__file__).resolve().parent.parent / "prompts" / "regras.md",
    )
    if not path:
        return (
            "Não invente preço, promoção ou telefone do polo. "
            "Mensalidade a partir de R$ 69,90. Esta conversa já é o atendimento."
        )
    return _sanitize_for_model(path.read_text(encoding="utf-8"), "regras")


@lru_cache
def load_conhecimento_lead() -> str:
    settings = get_settings()
    path = _resolve(
        settings.conhecimento_path,
        Path(__file__).resolve().parent.parent / "prompts" / "conhecimento_lead.md",
    )
    if not path:
        return "Mensalidade a partir de R$ 69,90. Pós EAD Faveni reconhecida pelo MEC."
    return _sanitize_for_model(path.read_text(encoding="utf-8"), "conhecimento_lead")


@lru_cache
def load_cursos() -> str:
    path = _resolve(
        "prompts/cursos.md",
        Path(__file__).resolve().parent.parent / "prompts" / "cursos.md",
    )
    if not path:
        return (
            "Cite somente cursos confirmados com o polo. "
            "Nunca invente nome, carga horária ou duração."
        )
    return _sanitize_for_model(path.read_text(encoding="utf-8"), "cursos")


@lru_cache
def load_precos() -> str:
    path = _resolve(
        "prompts/precos.md",
        Path(__file__).resolve().parent.parent / "prompts" / "precos.md",
    )
    if not path:
        return (
            "Mensalidade: use a tabela de valores por carga horária. "
            "Sem curso definido: a partir de R$ 69,90."
        )
    return _sanitize_for_model(path.read_text(encoding="utf-8"), "precos")


@lru_cache
def load_knowledge() -> str:
    """Compat: regras + conhecimento (sem notas internas)."""
    return load_regras() + "\n\n" + load_conhecimento_lead()
