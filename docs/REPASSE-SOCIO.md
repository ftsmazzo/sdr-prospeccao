# Repasse para o sócio — Demo Edu (Faveni / SDR)

**Data:** 2026-11-09  
**Objetivo deste texto:** alinhar o fechamento da demo e o que estamos construindo, em linguagem direta para encaminhar.

---

## Em uma frase

Vamos na reunião com o **Edu**: agente SDR no WhatsApp que conversa como humano, não alucina nem sai do fluxo, e conduz o lead até **aceitar a matrícula** e receber um **link placebo de checkout**.

---

## Por que isso importa

O cliente (polo Faveni Catanduva) já testou IAs que **desviavam do assunto e não fechavam**. O sucesso da reunião é ele **interagir com o Edu** e ver o agente chegar ao fim da venda — o que os outros não cumpriram.

---

## O que o Edu faz na demo

1. **Inbound** — responde quem chama no WhatsApp de teste.  
2. **Outbound** — dispara CTA de prospecção; quando a pessoa responde, continua a conversa até o fechamento.  
3. **Tom humanizado** — se sair do assunto, **não recusa como robô**; redireciona com uma frase empática de volta ao funil.  
4. **Áudio** — ouve áudio e responde em áudio; nos momentos-chave (abertura, objeção, fechamento) pode mandar áudio mesmo se o lead estiver em texto (ElevenLabs).  
5. **Conhecimento** — base Faveni (pós EAD, MEC, flexibilidade, mensalidade demo **a partir de R$ 69,90**). Canal = **nosso número de teste** (não o WhatsApp oficial deles).

---

## Critério de fechamento (importante)

| Contexto | Definição |
|---|---|
| **Demo (nosso)** | Lead aceita matrícula → Edu envia **link placebo de checkout/pagamento**. |
| **Produção (cliente)** | Critério oficial de “venda fechada” **ainda precisa ser definido com eles** (matrícula no sistema, pagamento real, etc.). |

Ou seja: na demo provamos o **caminho até o pagamento**; dados e sistemas reais entram depois que fecharmos conosco.

---

## O que não é prioridade agora

- CRM visual completo (só se sobrar tempo)  
- Fine-tuning  
- Número/WhatsApp oficial do polo  
- Integração real com AVA/matrícula Faveni  

---

## Stack (resumo)

Backend em código · orquestrador + agentes especializados · OpenRouter (vários modelos) · RAG em Postgres/pgvector · Redis · Evolution API · Mistral (PDF) · ElevenLabs (voz) · EasyPanel (Fabrica-IA).

Docs no repo: `PRD.md`, `TRD.md`, `FLUXO-APP.md`, `CONHECIMENTO-AGENTE-FAVENI.md`.

---

## Pedido ao sócio

Validar se concorda com o **fechamento via link placebo de checkout** como prova na reunião, e se o foco “agente impressionante > CRM” está alinhado antes de investirmos o tempo de build.
