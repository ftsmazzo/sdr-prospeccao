# PRD — Edu (SDR Prospecção)

> Product Requirements Document — o quê e por quê, não como.
> Fonte: [x] Entrevista com usuário  [ ] Leitura de código existente
> Apoio: Relata (áudios do projeto) + `docs/CONHECIMENTO-AGENTE-FAVENI.md`

**Data**: 2026-11-09  
**Responsável**: time do projeto sdr-prospeccao  
**Fase**: Demo para reunião comercial (atmosfera + prova de valor)

## 1. Resumo em uma frase

O **Edu** é um agente SDR humanizado no WhatsApp que prospecta e conduz leads de educação (Faveni Polo Catanduva) até o fechamento da matrícula, sem alucinar nem sair do fluxo — o que as soluções anteriores do cliente não entregaram.

## 2. Problema e contexto

- Problema real que motiva o projeto: o cliente (faculdade / polo com graduação e pós online) já testou agentes de IA para prospecção e fechamento; eles respondiam fora de contexto, desviavam do funil e não fechavam venda. A equipe de vendas existe, mas ele quer IA que aja de forma correta e humanizada. Ele também não consegue ficar o tempo todo na operação de implementação.
- Como é resolvido hoje: equipe humana de vendas + duas tentativas anteriores de agentes que falharam (anti-padrão a evitar).
- Por que agora: reunião comercial para demonstrar o potencial do nosso produto com algo testável ao vivo; criar atmosfera e dados demo até o fechamento do contrato (dados reais vêm depois).

## 3. Público-alvo

- Persona(s) principal(is) — **lead da demo**: “Profissional em evolução” (25–45, já graduado, busca pós EAD flexível e acessível). Detalhe em `docs/CONHECIMENTO-AGENTE-FAVENI.md`.
- Outros perfis de usuário relevantes:
  - **Comprador da demo (cliente)**: gestor do polo / operação comercial Faveni Catanduva — avalia se o Edu conversa como humano e fecha sem desviar.
  - **Operador futuro (pós-contrato)**: equipe de vendas que supervisiona o funil (fora do MVP da reunião, além de uma tela leve se couber).

## 4. Objetivos e métricas de sucesso

| Objetivo | Métrica | Meta |
|---|---|---|
| Impressionar na reunião | Interação ao vivo do cliente com o Edu | Cliente conversa com o agente e sente atendimento humano |
| Diferenciar das soluções que falharam | Aderência ao fluxo até fechamento | Edu não alucina, não desvia de assunto e chega ao fechamento da venda (matrícula / próximo passo concreto) |
| Provar valor do produto | Percepção de “pronto para piloto” | Cliente pede proposta / avançar após a demo |

## 5. Escopo

### Dentro do escopo (MVP da demo)

- Agente **Edu** conversacional no WhatsApp (Evolution API), tom humanizado
- Conhecimento base da Faveni Polo Catanduva (doc de conhecimento + RAG leve)
- Skills de quebra de objeção e fechamento
- Dados demo fixos: mensalidade **a partir de R$ 69,90**; canal WhatsApp da demo = **número de teste do nosso time** (Evolution) — **não** usamos o WhatsApp oficial do polo (sem acesso como cliente ainda)
- Fluxo comercial guiado: qualificar → recomendar → tratar objeção → fechar matrícula / CTA
- Painel demo: login, import de planilha, geração de CTA com IA (conhecimento da empresa), botão Enviar (2–3 números na apresentação — foco no agente tratar o retorno do CTA)
- (Desejável se o tempo permitir) CRM Kanban de funil

### Fora do escopo (por enquanto)

- Fine-tuning de modelo (avaliar só após conversas reais pós-contrato)
- Billing em produção / cobrança por tokens vs mensalidade (assunto comercial nosso × cliente, não da demo do Edu)
- Multi-polo / multi-tenant completo
- Integração real com AVA / matrícula oficial Faveni
- App mobile nativo
- Substituição total da equipe humana de vendas

## 6. Funcionalidades principais

| Funcionalidade | Prioridade (MVP/depois) | Descrição curta |
|---|---|---|
| Chat WhatsApp com Edu | MVP | Conversa natural, 1 pergunta por vez, memória da sessão |
| Base de conhecimento Faveni | MVP | Instituição, ofertas, FAQ, tom, contatos/preço demo |
| Skill quebra de objeção | MVP | Preço, validade MEC, tempo, “vou pensar”, etc. |
| Skill fechamento | MVP | Documentos, CTA WhatsApp/matrícula, próximo passo claro |
| Guardrails anti-alucinação | MVP | Só afirma o que está na base; não inventa preço/promo/número |
| Pipeline / CRM visual | Desejável demo / depois | Ver leads andando sozinhos no funil |
| Hand-off humano | Depois | Transferir caso complexo para vendedor |
| Autonomia full (disparo em massa, nurturing) | Depois | Pós-contrato, com dados e regras reais |

## 7. Restrições de negócio

- Prazo: demo pronta para a reunião comercial (o quanto antes, com qualidade de conversa acima de amplitude de features).
- Orçamento: stack já disponível / preferida (EasyPanel, Evolution, Redis, Postgres/pgvector) — detalhar no TRD.
- Legais/regulatórias (ex. LGPD): demo com dados fictícios ou leads de teste; em produção, consentimento e política de retenção de conversas (registrar no TRD).

## 8. Riscos e premissas

- Premissa: o cliente julga sucesso pela **qualidade da conversa até o fechamento**, não pela quantidade de telas — se a demo for só UI sem diálogo sólido, a reunião falha.
- Premissa: dados demo (telefone + R$ 69,90) bastam para atmosfera; dados oficiais virão após fechamento.
- Premissa: WhatsApp via Evolution API no EasyPanel está disponível e estável para a demo.
- Risco: alucinação / desvio de fluxo (mesmo problema dos concorrentes) — impacto alto; mitigar com RAG + skills + guardrails rígidos.
- Risco: latência ou queda do WhatsApp na hora da reunião — impacto alto; ter fallback (webchat espelhando o mesmo agente).
- Risco: expectativa de CRM completo na primeira reunião — impacto médio; priorizar o agente; CRM só se não comprometer o diálogo.

---

## Gaps & Recomendações (preencher só no Modo B — análise de repo existente)

_Não aplicável (Modo A — projeto novo)._
