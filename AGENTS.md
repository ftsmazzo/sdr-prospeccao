# AGENTS.md — Edu SDR

Fonte única de regras do projeto. `.cursor/rules` deve apontar para cá, sem duplicar texto longo.

## Produto

- Agente **Edu**: conversa humanizada, sem alucinar, sem desviar do funil até checkout placebo.
- Demo: número WhatsApp de **teste/emprestado**; dados Faveni em `docs/CONHECIMENTO-AGENTE-FAVENI.md`.
- Outbound CTA é **momento especial** (`origin=outbound_cta`).

## Stack

- Backend FastAPI; OpenRouter multi-modelo; Evolution; Redis; Postgres+pgvector; ElevenLabs; deploy EasyPanel **Fabrica-IA**.
- Secrets só em env — nunca commitados.
- Repo GitHub está **público** (exigência do deploy EasyPanel com o token atual). Não colocar credenciais, `.env` nem dumps no git.

## Qualidade / segurança

- Não inventar preço, promoção ou telefone do polo.
- Webhook Evolution validado por secret.
- `/health` obrigatório em todo deploy.
- Preferir Ruff em Python; erros: GlitchTip (DSN via `SENTRY_DSN`) quando houver; uptime: Uptime Kuma em `/health`.

## Fluxo de trabalho

- Issues/PRs pequenos alinhados às fases do `docs/PLANO-IMPLEMENTACAO.md`.
- MVP: inbound → fechamento; depois voz; depois painel CTA; Kanban só se sobrar tempo.
