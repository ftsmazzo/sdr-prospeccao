# Notas internas — Edu / demo Faveni (NÃO entra no prompt do agente)

> Este arquivo é para o time. O código **não** carrega este conteúdo no modelo.

## Contexto da demo

- Número WhatsApp: teste/emprestado via Evolution (instance `poli` no projeto poli2).
- Não conectar nem apresentar o WhatsApp oficial do polo — ainda sem acesso como cliente.
- Repo GitHub é **público** (exigência EasyPanel). Secrets só em env / EasyPanel.
- Fechamento demo = checkout placebo + contrato PDF demonstrativo.

## Telefone oficial do polo (NÃO citar na demo)

- Referência histórica do site: **(17) 98819-6906**
- Motivo de não citar: confundiria com o canal de teste do Edu.

## Tabela de preços (demo)

- Fonte injetada no modelo: `prompts/precos.md` (faixas por carga horária).
- **Esta tabela é de demonstração** e deve ser substituída pela tabela real do cliente antes de produção.
- Código de resolução: `app/pricing.py` (checkout, PDF e fiscal da sim usam a mesma fonte).

## Claims a evitar no agente

- “Nota máxima no MEC” (claim de perfil LinkedIn — não usar como fato no prompt do lead).
- Urgência/escassez inventada; desconto/bolsa fora da tabela `precos.md`.

## Modelo LLM

- Padrão: `OPENROUTER_MODEL=anthropic/claude-sonnet-5` (melhor fluxo até contrato na demo).
- Alternativa: `openai/gpt-4.1-mini` — só trocar a env; sem redeploy de código.
- Agente: tool calling forçado (`responder`) + `cache_control` na parte fixa do system prompt; temperature omitida no Sonnet 5.
- Probe local (máx. 3 chamadas): `python scripts/probe_tool_json.py`.

## Operação

- Webhook: `POST /webhooks/evolution` (+ opcional `/{secret}` no path).
- Header preferido: `X-Webhook-Secret`.
- `WEBHOOK_SECRET_ENFORCE=false` até o secret estar confirmado nos logs; depois `true`.
- Ver script: `scripts/evolution_webhook_secret.sh` (você executa; não reinicia a instance).

## Pós-venda (demonstração)

- Fonte injetada nas etapas `contrato_enviado` / `matriculado`: `prompts/pos_venda.md`.
- Prazos e canais ali são **de demonstração** (substituir pelos reais do polo antes de produção).
- A agente não inventa outros prazos nem promete “avisar quando liberar”.

## Pós-contrato (fora do MVP)

- Dados oficiais do polo, storage de documentos, OCR, CRM Kanban, etc.
