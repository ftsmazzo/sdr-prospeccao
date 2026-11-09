# Conhecimento Base do Agente — Faveni Polo Catanduva

> **Este arquivo foi dividido.** Não edite conteúdo longo aqui.

| Arquivo | Uso |
|---|---|
| [`prompts/regras.md`](../prompts/regras.md) | Comportamento e limites — entra no system prompt |
| [`prompts/conhecimento_lead.md`](../prompts/conhecimento_lead.md) | Fatos que o lead pode ouvir — entra no system prompt |
| [`docs/notas-internas.md`](notas-internas.md) | Demo, telefone do polo, notas de time — **nunca** no modelo |

A jornada de fechamento (marcadores `LEAD_DATA` / `FOLLOWUP_DOC` / `CHECKOUT_READY`) fica no `SYSTEM_TEMPLATE` em `app/orchestrator.py`, em um único lugar.
