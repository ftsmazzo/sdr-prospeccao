# UI/UX Design — Edu (SDR Prospecção)

> Direção visual e de experiência.
> Fonte: [x] Entrevista com usuário  [ ] Leitura de código existente
> Depende de: [Fluxo do App](FLUXO-APP.md)

**Data**: 2026-11-09

## 1. Referências e tom

- Referências visuais/concorrentes: WhatsApp como canal principal (UI nativa do app); web própria só para checkout placebo e, se sobrar tempo, CRM. Sem copiar layout de concorrente de IA.
- Tom da marca: **limpo / educacional** — confiança, clareza, acolhimento. Evitar visual “robô / neon / IA genérica”. O Edu deve parecer consultor de matrícula, não chatbot de suporte.

## 2. Plataformas-alvo

- [x] Web responsivo (checkout placebo; CRM opcional)
- [ ] PWA
- [ ] Mobile nativo (iOS/Android)
- [ ] Desktop
- **Canal principal da demo:** WhatsApp (mobile), número de teste

## 3. Sistema visual

- Paleta de cores (direção):
  - Base clara (branco / off-white)
  - Primária educacional sóbria (azul ou verde-institucional — **a definir no implemento**, sem roxo “AI default”)
  - Acento para CTA de matrícula / pagamento
  - Texto escuro legível; contraste alto em botões
- Tipografia: sans humanista legível (ex. fonte do sistema no WhatsApp; na web, uma família limpa tipo “DM Sans” / “Source Sans” — evitar Inter como único default se houver opção rápida)
- Componentes centrais:
  - **Chat WhatsApp** (texto + áudio) — experiência #1
  - **Página de checkout placebo** — experiência web #1 da demo
  - **Kanban de funil** — CRM desejável depois (não bloqueia demo)
  - Sem dashboard denso na primeira entrega

### Identidade do Edu no WhatsApp

- Nome de exibição: **Edu**
- **Foto/avatar completo** (pessoa/consultor educacional — gerar ou escolher asset antes da reunião)
- Status/recado curto (opcional): ex. “Consultoria de matrícula · Faveni” (atmosfera demo)
- Mensagens: curtas, 1 pergunta por vez; áudio nos momentos-chave e quando o lead manda áudio

## 4. Acessibilidade

- Requisitos específicos: pt-BR claro; textos curtos no WhatsApp; na página de checkout, contraste WCAG AA como alvo prático; botões grandes o suficiente para toque no mobile.
- Áudio: sempre ter equivalente em texto se TTS falhar; não depender só de voz para o CTA final.

## 5. Telas principais

| Tela | Jornada relacionada | Estado |
|---|---|---|
| Conversa WhatsApp (Edu) | Inbound / Outbound / Fechamento | Aprovado (prioridade máxima) |
| Checkout placebo — “Matrícula Faveni — pagamento simulado” | Fechamento demo | Aprovado |
| Login do painel demo | Outbound (operador) | Aprovado (necessário ao fluxo de CTA) |
| Import de planilha + gerar CTA (IA) + Enviar | Outbound (2–3 números na demo) | Aprovado — atmosfera; foco no agente ao responder |
| (Depois) CRM Kanban — Novo → Em conversa → Objeção → Fechado | Operação / autonomia visual | Ideia aprovada; **adiado** |
| (Depois) Inbox/chat no CRM | Operação | Fora por enquanto (kanban primeiro, se houver tempo) |

### Checkout placebo (especificação curta)

- Título: **Matrícula Faveni — pagamento simulado**
- Mostrar: curso escolhido (ou “Pós-Graduação EAD”), valor âncora **a partir de R$ 69,90**, nome do lead se conhecido
- CTA: botão “Confirmar pagamento (demo)” → estado de sucesso (“Matrícula registrada — demonstração”)
- Rodapé discreto: aviso de que é **simulação para demonstração**, sem cobrança real
- Visual: limpo/educacional, mobile-first (lead abre pelo WhatsApp)

### CRM Kanban (quando formos fazer)

- Colunas sugeridas: **Novo → Em conversa → Objeção → Fechado (checkout)**
- Card: nome/telefone, último estágio, indicador se último turno foi áudio
- Sem cards no “hero”; tela única operacional

---

## Gaps & Recomendações (preencher só no Modo B — análise de repo existente)

_Não aplicável (Modo A — projeto novo)._
