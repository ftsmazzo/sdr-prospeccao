# Plano de Implementação — Edu (SDR Prospecção)

> Roteiro de execução. No Modo B, funciona como "Plano de Melhoria".
> Depende de: todos os documentos anteriores.

**Data**: 2026-11-09

## 1. MVP

O que precisa existir para o produto já gerar valor/ser testável **na reunião**:

- Backend + orquestrador + agentes (qualificação, RAG, objeção, fechamento, **retorno de CTA**)
- WhatsApp via Evolution no **número de teste**
- Conhecimento Faveni ingerido (doc + pgvector)
- Inbound humanizado até **checkout placebo** (`/checkout/{token}`)
- Painel: login · import planilha · gerar CTA com IA · botão Enviar (2–3 números)
- STT (ouvir) + TTS ElevenLabs (responder áudio / momentos-chave)
- Guardrails: não alucinar preço/promo; não desviar do funil
- Deploy EasyPanel (**Fabrica-IA**) com `/health`

**Fora do MVP da reunião:** Kanban CRM completo, fine-tune, áudio em arquivo, número oficial do polo, disparo em massa.

## 2. Fases seguintes

| Fase | Escopo | Prioridade | Dependências |
|---|---|---|---|
| **0 — Fundações** | Repo, scaffold FastAPI (sugestão), Docker, Postgres+pgvector, Redis, `/health`, projeto EasyPanel Fabrica-IA, envs (OpenRouter, Evolution, ElevenLabs) | Alta | Acesso Fabrica-IA, chaves API, Evolution com número teste |
| **1 — Cérebro Edu (inbound)** | Orquestrador multi-modelo OpenRouter, RAG, skills objeção/fechamento, webhook WhatsApp, checkout placebo, ingestão `CONHECIMENTO-AGENTE-FAVENI.md` | Alta | Fase 0 |
| **2 — Voz** | STT em áudios inbound; TTS ElevenLabs (espelhar áudio + momentos-chave); fallback texto | Alta | Fase 1, conta ElevenLabs |
| **3 — Outbound assistido** | Login, import CSV/XLSX, generate-cta (IA + corpus), send controlado, flag `outbound_cta` + skill de retorno | Alta | Fase 1 |
| **4 — Polimento demo** | Avatar Edu, scripts de ensaio (inbound + outbound), logs AgentRun, página checkout visual limpa | Média | Fases 1–3 |
| **5 — CRM Kanban** (se sobrar tempo) | Colunas Novo → Em conversa → Objeção → Fechado | Baixa | Fase 1 |
| **6 — Pós-contrato** | Dados reais do polo, critério de fechamento oficial, mídia em storage se cliente pedir, PDF/Mistral em escala | — | Cliente fechado |

## 3. Marcos externos

- Data de lançamento/demo: **a confirmar** (reunião comercial com Faveni Polo Catanduva)
- Conta **ElevenLabs** a criar
- Número WhatsApp de **teste** + Evolution estáveis
- Chave **OpenRouter** (e Mistral se rota separada para PDF)
- Validar com sócio o fechamento via **link placebo** (`docs/REPASSE-SOCIO.md`)

## 4. Critério de "pronto" por fase

- **Fase 0:** app sobe no EasyPanel; `GET /health` 200; Postgres e Redis conectados.
- **Fase 1:** conversa inbound de teste chega ao **checkout confirmado** sem alucinar e sem sair do funil (ensaio de 5–10 min).
- **Fase 2:** lead manda áudio → Edu responde áudio; em fechamento, Edu pode mandar áudio de CTA mesmo em thread texto.
- **Fase 3:** importar 2–3 números, gerar CTA, enviar, responder como lead e ver o Edu **continuar o CTA** (não resetar conversa) até o placebo.
- **Fase 4:** roteiro de reunião ensaiado (inbound + outbound + áudio + checkout); avatar no WhatsApp.
- **Fase 5 (opcional):** kanban reflete estágio da Conversation em tempo quase real.
- **Sucesso da reunião (PRD):** cliente interage com o Edu e vê condução até o fechamento — o que as soluções anteriores não cumpriram.

### Ordem de build sugerida (se o tempo apertar)

1. Inbound texto → fechamento placebo (obrigatório)  
2. Guardrails / RAG (obrigatório)  
3. Outbound CTA + skill de retorno (forte na demo)  
4. Áudio (wow factor)  
5. Visual checkout / avatar  
6. Kanban  

---

## Modo B — Plano de Melhoria

_Não aplicável (Modo A — projeto novo)._
