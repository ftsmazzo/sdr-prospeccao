"""
Validação 0.4 — no máximo 3 chamadas reais OpenRouter com tool calling.

Uso (local, com .env):
  python scripts/probe_tool_json.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# carrega .env simples
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

from app.clients.openrouter import OpenRouterClient
from app.config import get_settings
from app.prompt_builder import build_cached_system_message, build_system_prompt_parts
from app.schemas import RESPONDER_TOOL, RESPONDER_TOOL_CHOICE, parse_agent_response

# Preços aproximados Sonnet 5 (USD / 1M)
_IN = 2.00
_OUT = 10.00
MAX_CALLS = 3


def _cost(usage: dict) -> float:
    pin = int(usage.get("prompt_tokens") or 0)
    pout = int(usage.get("completion_tokens") or 0)
    return (pin * _IN + pout * _OUT) / 1_000_000


async def one_call(client: OpenRouterClient, n: int, user: str) -> bool:
    fixed, variable = build_system_prompt_parts(
        etapa="abertura",
        lead_state={"graduacao": None, "curso_escolhido": None, "aceite_matricula": False},
        meta_flags={},
        agent_name="Clara",
        agent_gender="f",
    )
    messages = [
        build_cached_system_message(fixed, variable),
        {"role": "user", "content": user},
    ]
    raw = await client.chat_tool(
        messages,
        tools=[RESPONDER_TOOL],
        tool_choice=RESPONDER_TOOL_CHOICE,
        temperature=0.4,
    )
    usage = dict(client.last_usage or {})
    parsed = parse_agent_response(raw)
    usd = _cost(usage)
    print(f"\n=== chamada {n}/{MAX_CALLS} ===")
    print(f"usage={usage}")
    print(f"custo_estimado_usd={usd:.6f}")
    if not parsed:
        print("FALHA: não parseou AgentResponse")
        print("bruto=", (raw or "")[:400])
        return False
    print(f"reply={parsed.reply[:160]!r}")
    print(f"offer={parsed.offer}")
    print(f"action={parsed.action}")
    return True


async def main() -> int:
    get_settings.cache_clear()
    s = get_settings()
    s.openrouter_model = "anthropic/claude-sonnet-5"
    if not s.openrouter_api_key:
        print("ABORT: OPENROUTER_API_KEY ausente")
        return 2
    client = OpenRouterClient(s)
    prompts = [
        "Oi, quero algo na área da saúde, talvez estética",
        "Já tenho graduação concluída. Me interesso por Autismo.",
        "Sim",
    ]
    ok_all = True
    total = 0.0
    for i, user in enumerate(prompts[:MAX_CALLS], 1):
        ok = await one_call(client, i, user)
        total += _cost(client.last_usage or {})
        if not ok:
            ok_all = False
            break
    print(f"\nTOTAL estimado US$ {total:.6f} em até {MAX_CALLS} chamadas")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
