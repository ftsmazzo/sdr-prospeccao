# Esquema Backend — Edu (SDR Prospecção)

> Modelagem de dados e API.
> Fonte: [x] Entrevista com usuário  [ ] Leitura de código existente
> Depende de: [TRD](TRD.md)

**Data**: 2026-11-09

## 1. Entidades principais

| Entidade | Campos-chave | Relacionamentos |
|---|---|---|
| **User** (operador demo) | id, email, password_hash, name, created_at | cria Campaigns, importa Leads |
| **Lead** | id, phone (E.164), name?, source (`inbound` \| `import` \| `manual`), meta JSON, created_at | 1:N Conversations; N:1 Campaign (opcional) |
| **Campaign** | id, name, cta_text, cta_brief (norte do operador), status (`draft` \| `ready` \| `sent`), created_by, created_at | N:1 User; 1:N CampaignRecipients; gera mensagens outbound |
| **CampaignRecipient** | id, campaign_id, lead_id, status (`pending` \| `sent` \| `replied` \| `error`), sent_at? | N:1 Campaign, Lead |
| **Conversation** | id, lead_id, channel (`whatsapp`), origin (`inbound` \| `outbound_cta`), campaign_id?, stage (`new` \| `qualifying` \| `recommending` \| `objection` \| `closing` \| `closed`), created_at | N:1 Lead; 1:N Messages |
| **Message** | id, conversation_id, direction (`in` \| `out`), modality (`text` \| `audio`), text_content, audio_transcript?, provider_message_id?, created_at | N:1 Conversation |
| **KnowledgeDocument** | id, title, source, raw_text, created_at | 1:N KnowledgeChunk |
| **KnowledgeChunk** | id, document_id, content, embedding (pgvector), metadata JSON | N:1 KnowledgeDocument |
| **CheckoutSession** | id, token (único), lead_id, conversation_id, course_label, amount_label (ex. “a partir de R$ 69,90”), status (`pending` \| `confirmed_demo`), confirmed_at? | N:1 Lead, Conversation |
| **AgentRun** (log demo) | id, conversation_id, intent, agent_name, model, chunk_ids[], latency_ms, created_at | N:1 Conversation |

### Notas de modelagem

- **Áudio na demo:** persistir **apenas transcrição** (`audio_transcript` / `text_content`). Arquivo de áudio = decidir com o cliente no produto final.
- **Outbound é momento especial:** `Conversation.origin = outbound_cta` + `campaign_id` obrigam o orquestrador a usar skill/contexto de “retorno de CTA” (não tratar como inbound frio).
- Volume da apresentação: **2 ou 3 números** — campanha existe para mostrar o fluxo, não para disparo em massa.

## 2. Autenticação e autorização

- Método: **login próprio** (email + senha) para o painel demo (operador / cliente na reunião).
- Níveis de permissão/papéis (demo):
  - **Operador:** importar planilha, gerar CTA com IA, enviar para recipients selecionados, ver conversas/logs leves.
  - **Público:** webhook Evolution (validação por secret); checkout `/checkout/{token}` sem login.
- Sessão: cookie/JWT httpOnly (**sugestão**); secrets no EasyPanel.

## 3. Endpoints/ações principais

| Endpoint/Ação | Método | Autenticado? | Regra de negócio relevante |
|---|---|---|---|
| `POST /auth/login` | POST | Não | Emite sessão do operador |
| `POST /leads/import` | POST (CSV/XLSX) | Sim | Upsert por telefone; amarra à campanha draft se enviada |
| `POST /campaigns` | POST | Sim | Cria campanha com `cta_brief` (norte do humano) |
| `POST /campaigns/{id}/generate-cta` | POST | Sim | IA usa brief + conhecimento da empresa (mesmo corpus do Edu) e propõe `cta_text` editável |
| `PATCH /campaigns/{id}` | PATCH | Sim | Operador ajusta o CTA antes de enviar |
| `POST /campaigns/{id}/send` | POST | Sim | Envia só aos recipients escolhidos (demo: 2–3); **não** disparo imediato automático ao gerar CTA |
| `POST /webhooks/evolution` | POST | Secret | Ingresso de msgs; cria/atualiza Conversation; se reply a campaign → `origin=outbound_cta` |
| `POST /internal/orchestrate` | interno | — | Orquestrador: intenção → agente → RAG → resposta (texto; TTS se áudio) |
| `GET /checkout/{token}` | GET | Não | Página placebo; token opaco de uso único/limitado |
| `POST /checkout/{token}/confirm` | POST | Não | Marca `confirmed_demo`; Conversation → `closed` |
| `GET /health` | GET | Não | Healthcheck deploy |

## 4. Processamento assíncrono

- **Webhook Evolution** → enfileirar processamento (Redis/fila leve ou worker) para não estourar timeout.
- Jobs: STT (transcrever áudio inbound) → orquestração → (opcional) TTS ElevenLabs → envio WhatsApp.
- `generate-cta`: pode ser síncrono na demo (1 chamada LLM); se lento, job + polling.
- **Sem cron de disparo em massa** na demo. Envio só no botão **Enviar**, sob controle humano.
- Follow-up automático agressivo: fora do escopo da demo.

## 5. Armazenamento

- Tipo de dados:
  - Estruturado: Postgres (leads, campanhas, conversas, mensagens, checkout, users).
  - Vetorial: pgvector em `KnowledgeChunk.embedding`.
  - Sessão/fila: Redis.
  - Mídia: **não guardar áudio bruto na demo** (só texto/transcrição).
  - Sensíveis: telefone, nome, conteúdo de conversa — acesso autenticado no painel; checkout só por token.
- Volume esperado: dezenas de leads/conversas na demo; corpus de conhecimento pequeno (doc Faveni + PDFs ingeridos).

### Comportamento do orquestrador no retorno de CTA (regra de negócio)

Quando `origin = outbound_cta`:

1. Carregar `Campaign.cta_text` + `cta_brief` na memória da sessão.
2. Agente reconhece que a pessoa está **reagindo a um convite específico** (tom de continuidade, não de primeiro contato genérico).
3. Avançar rápido para qualificação/recomendação alinhada ao CTA, sem “Oi, em que posso ajudar?” vazio.
4. Seguir skills de objeção/fechamento até checkout placebo.

---

## Gaps & Recomendações (preencher só no Modo B — análise de repo existente)

_Não aplicável (Modo A — projeto novo)._
