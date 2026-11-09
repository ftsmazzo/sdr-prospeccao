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

## Claims a evitar no agente

- “Nota máxima no MEC” (claim de perfil LinkedIn — não usar como fato no prompt do lead).
- Urgência/escassez inventada; desconto/bolsa não listados.

## Operação

- Webhook: `POST /webhooks/evolution` (+ opcional `/{secret}` no path).
- Header preferido: `X-Webhook-Secret`.
- `WEBHOOK_SECRET_ENFORCE=false` até o secret estar confirmado nos logs; depois `true`.
- Ver script: `scripts/evolution_webhook_secret.sh` (você executa; não reinicia a instance).

## Pós-contrato (fora do MVP)

- Dados oficiais do polo, storage de documentos, OCR, CRM Kanban, etc.
