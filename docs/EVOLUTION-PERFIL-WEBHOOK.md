# Evolution — perfil Edu + webhook (número emprestado)

## Resposta direta

**Sim.** Pela Evolution API dá para alterar:

| O quê | Endpoint (v1/v2 típico) | Body |
|---|---|---|
| Nome | `POST /chat/updateProfileName/{instance}` | `{ "name": "Edu" }` |
| Status / recado | `POST /chat/updateProfileStatus/{instance}` | `{ "status": "Consultoria de matrícula · Faveni" }` |
| Foto | `POST /chat/updateProfilePicture/{instance}` | `{ "picture": "https://url-publica-da-imagem.jpg" }` **ou** multipart `file` (conforme versão) |
| Remover foto | `DELETE /chat/removeProfilePicture/{instance}` | — |

Header: `apikey: <EVOLUTION_API_KEY>`

> A URL base e o nome da **instance** são os da Evolution onde o número está conectado. Sem celular na mão, dá para reapontar só o **webhook** e o perfil via API — o QR/pareamento só seria necessário se a sessão cair.

## Webhook temporário (projeto parado → Edu)

1. Anote a URL/webhook atuais do projeto parado (para reverter depois).
2. Quando o Edu tiver domínio público, aponte o webhook da instance para:
   `https://<dominio-edu>/webhooks/evolution`
3. Eventos mínimos: mensagens recebidas (e envio se quiser espelhar status).
4. Após a demo, restaure o webhook do projeto original.

### Secret do webhook (sem logout / sem QR)

Evolution API 2.x (ex. **2.3.7**) aceita `headers` no `POST /webhook/set/{instance}`.  
Body aninhado: `{ "webhook": { "enabled", "url", "events", "headers", "byEvents", "base64" } }`.  
**Não** use o dashboard se ele não expõe headers — use a API.  
`show` não sobrescreve backup existente (salva com timestamp).

Script pronto (você executa; o agente não roda contra a instance):

```bash
export EVOLUTION_BASE_URL="https://SUA-EVOLUTION"
export EVOLUTION_API_KEY="..."
export EVOLUTION_INSTANCE="poli"
export WEBHOOK_SECRET="cole-aqui-o-mesmo-valor-do-EasyPanel"

chmod +x scripts/evolution_webhook_secret.sh
./scripts/evolution_webhook_secret.sh show           # consulta + backup
./scripts/evolution_webhook_secret.sh apply-header   # preferido
# se headers não funcionarem:
# ./scripts/evolution_webhook_secret.sh apply-path
./scripts/evolution_webhook_secret.sh undo           # volta ao backup
```

No Edu: deixe `WEBHOOK_SECRET_ENFORCE=false` até ver nos logs `secret=ok`; depois `true`.  
Admin da API: só header `X-Admin-Secret` (nunca query string).

### Script de perfil (sem logout / sem QR)

Mesmo padrão do webhook — você executa; o agente não roda contra a instance:

```bash
export EVOLUTION_BASE_URL="https://SUA-EVOLUTION"
export EVOLUTION_API_KEY="..."
export EVOLUTION_INSTANCE="poli"
export PROFILE_NAME="${AGENT_NAME:-Edu}"
export PROFILE_PICTURE_URL="https://SEU_HOST/avatar.jpg"
export PROFILE_STATUS="Consultoria de matrícula · Faveni"

chmod +x scripts/evolution_profile.sh
./scripts/evolution_profile.sh show
./scripts/evolution_profile.sh apply-name
./scripts/evolution_profile.sh apply-picture
./scripts/evolution_profile.sh apply-status
```

### Exemplo curl (ajuste BASE / INSTANCE / KEY)

```bash
# Nome
curl -X POST "$EVOLUTION_BASE_URL/chat/updateProfileName/$EVOLUTION_INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Edu"}'

# Status
curl -X POST "$EVOLUTION_BASE_URL/chat/updateProfileStatus/$EVOLUTION_INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"Consultoria de matrícula · Faveni"}'

# Foto (URL pública HTTPS — JPG/PNG)
curl -X POST "$EVOLUTION_BASE_URL/chat/updateProfilePicture/$EVOLUTION_INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"picture":"https://SEU_HOST/edu-avatar.jpg"}'
```

## O que preciso de você para executar

- `EVOLUTION_BASE_URL` (ex. `https://evolution.seudominio.com`)
- Nome da **instance**
- `EVOLUTION_API_KEY`
- Qual instance/número vamos emprestar (projeto parado)
- Avatar: URL pública ou arquivo (eu gero um asset “consultor educacional” se quiser)

Com isso eu altero perfil e, assim que o `/webhooks/evolution` estiver no ar, ajudo a apontar o webhook.
