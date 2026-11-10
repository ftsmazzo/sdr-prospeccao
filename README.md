# Edu — SDR Prospecção (demo)

Agente SDR humanizado no WhatsApp para demo comercial (Faveni Polo Catanduva).

Documentação de produto em [`docs/`](docs/). Comece pelo [PRD](docs/PRD.md) e o [Plano](docs/PLANO-IMPLEMENTACAO.md).

## Dev local

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
curl http://127.0.0.1:8000/health
```

## Stack (resumo)

FastAPI · OpenRouter (multi-modelo) · Evolution API · Redis · Postgres/pgvector · ElevenLabs · EasyPanel (Fabrica-IA).

Modelo padrão da agente: `anthropic/claude-sonnet-5` (`OPENROUTER_MODEL`). Alternativa mais barata: `openai/gpt-4.1-mini` (só trocar a variável no EasyPanel / `.env`).

## Evolution (número emprestado)

Ver [docs/EVOLUTION-PERFIL-WEBHOOK.md](docs/EVOLUTION-PERFIL-WEBHOOK.md) — nome, avatar e status via API; webhook apontado para este serviço.
