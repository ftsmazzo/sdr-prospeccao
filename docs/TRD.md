# TRD — Edu (SDR Prospecção)

> Technical Requirements Document — traduz o PRD em decisões técnicas.
> Fonte: [x] Entrevista com usuário  [ ] Leitura de código existente
> Depende de: [PRD](PRD.md)

**Data**: 2026-11-09

## 1. Stack tecnológica

| Camada | Tecnologia | Motivo/restrição |
|---|---|---|
| Frontend | Web mínima (React/Next) — **só se sobrar tempo** | CRM/pipeline visual é desejável, não bloqueia a demo |
| Backend | API própria em código (**sugestão:** Python + FastAPI) | Mais controle, guardrails e orquestração multi-agente; alternativa TS/Nest se o time preferir |
| Orquestração | **Orquestrador + agentes especializados** (código) | Um “cérebro” roteia a jornada; especialistas executam tarefas (RAG, objeção, fechamento, mídia) |
| LLMs | **OpenRouter** (vários modelos) | Um gateway; modelos leves p/ retrieval/classificação; modelos fortes p/ compreender jornada e responder |
| PDF | **Mistral** (via OpenRouter ou API Mistral) | Leitura/extração de PDFs (materiais, editais, folders) para enriquecer a base |
| Áudio → texto (STT) | Whisper ou equivalente disponível no OpenRouter | Lead manda áudio no WhatsApp; Edu “escuta” |
| Texto → áudio (TTS) | **ElevenLabs** (conta a criar) | Resposta em áudio humanizada/natural quando fizer sentido |
| Canal | **Evolution API** (WhatsApp) | Número de **teste do nosso time** na demo |
| Memória de sessão | **Redis** | Contexto curto da conversa, locks, filas leves |
| Dados + RAG | **PostgreSQL + pgvector** | Conhecimento Faveni, embeddings, histórico resumido |
| Infra/Deploy | **EasyPanel via MCP Fabrica-IA** | Projeto isolado: app, worker (opcional), Redis, Postgres |

### Estratégia multi-modelo (OpenRouter)

| Papel | Tipo de modelo | Responsabilidade |
|---|---|---|
| Orquestrador / roteador | Médio | Classificar intenção, estágio do funil, escolher agente/skill |
| Retrieval / ranking RAG | Leve / barato | Consultar pgvector, filtrar chunks relevantes |
| Conversação + jornada | Forte | Entender contexto, responder como humano, avançar ao fechamento |
| Quebra de objeção / fechamento | Forte (pode ser o mesmo conversacional) | Skills dedicadas com prompts fechados |
| Visão de PDF | Mistral (document) | Extrair texto/estrutura de PDFs ingeridos |
| STT | Whisper (ou similar) | Transcrever áudios recebidos |
| TTS | ElevenLabs (fora do OpenRouter) | Sintetizar resposta em áudio |

> **Fora da demo:** fine-tuning. Prioridade = orquestração + RAG + guardrails + voz.

## 2. Integrações externas

| Integração | Finalidade | Observações |
|---|---|---|
| OpenRouter | Chat, roteamento multi-modelo, STT/PDF conforme disponibilidade | Chaves em env; nunca no repo |
| Mistral | Leitura de PDFs | Via OpenRouter se houver rota; senão API Mistral direta |
| ElevenLabs | TTS humanizado | Conta a criar; voz escolhida alinhada ao tom do Edu |
| Evolution API | Envio/recebimento WhatsApp (texto e mídia) | Webhook → backend; número de teste |
| EasyPanel (Fabrica-IA) | Provisionar projeto, Postgres, Redis, app | Serviços isolados; não reutilizar banco de outro projeto |

## 3. Requisitos não-funcionais

- Performance (ex. tempo de resposta esperado): texto &lt; ~5–8s na demo; áudio (STT+LLM+TTS) pode levar mais — indicar “ouvindo/respondendo…” se necessário.
- Escalabilidade (volume esperado de usuários/dados): demo / piloto baixo volume (dezenas de conversas); desenhar para crescer com filas depois.
- Segurança (autenticação, criptografia, dados sensíveis): secrets só em env do EasyPanel; webhook Evolution com validação; painel CRM (se existir) com auth básica.
- Compliance (LGPD, setor regulado): demo com leads de teste; avisar que produção exigirá base legal/consentimento e retenção de áudio/texto.
- Disponibilidade (SLA esperado, se houver): melhor esforço para a reunião; fallback webchat com o mesmo orquestrador se WhatsApp falhar (**sugestão**).
- Internacionalização/idiomas: pt-BR apenas.

## 4. Ambiente e deploy

- Onde roda (cloud/on-premise/serverless): VPS/orquestração via **EasyPanel**.
- Provedor (se já definido): **Fabrica-IA** (MCP) — criar projeto dedicado ao repositório.
- CI/CD: deploy a partir do GitHub (`autoDeploy`) quando o repo existir; scaffold mínimo com `/health`.

## 5. Restrições herdadas

- Sistemas legados a integrar: nenhum na demo (sem AVA/matrícula oficial Faveni).
- Decisões técnicas já tomadas e não-negociáveis:
  - Backend em **código** (não n8n como orquestrador principal)
  - **OpenRouter** multi-modelo
  - **Orquestrador + agentes especializados**
  - **Redis + Postgres/pgvector**
  - **Evolution API** + número de teste
  - **Mistral** para PDFs; **ElevenLabs** para áudio de saída
  - Foco no **agente impressionante**; CRM só se sobrar tempo
  - Infra no **Fabrica-IA**

## 6. Manutenção

- Quem mantém o código após o lançamento: time que está construindo a demo (mesmo repositório).
- Nível de complexidade aceitável dado quem mantém: orquestração explícita e skills/arquivos de prompt versionados; evitar framework mágico opaco demais. Preferir módulos claros: `orchestrator`, `agents/*`, `rag`, `channels/whatsapp`, `media/stt|tts|pdf`.

### Guardrails técnicos (amarrados ao PRD)

- Respostas ancoradas em RAG + `CONHECIMENTO-AGENTE-FAVENI.md`
- Skills de objeção/fechamento como passos explícitos do orquestrador (não “um prompt só”)
- Proibir inventar preço/promo/telefone do polo
- Log da cadeia: intenção → agente → chunks usados → resposta (para debug na demo)

---

## Gaps & Recomendações (preencher só no Modo B — análise de repo existente)

_Não aplicável (Modo A — projeto novo)._
