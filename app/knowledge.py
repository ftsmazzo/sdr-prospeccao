from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@lru_cache
def load_knowledge() -> str:
    settings = get_settings()
    path = Path(settings.knowledge_path)
    if not path.is_file():
        # fallback inside container / local
        for candidate in (
            Path("docs/CONHECIMENTO-AGENTE-FAVENI.md"),
            Path(__file__).resolve().parent.parent / "docs" / "CONHECIMENTO-AGENTE-FAVENI.md",
        ):
            if candidate.is_file():
                path = candidate
                break
    if not path.is_file():
        return "Base de conhecimento indisponível. Mensalidade a partir de R$ 69,90. Pós EAD Faveni reconhecida pelo MEC."
    return path.read_text(encoding="utf-8")
