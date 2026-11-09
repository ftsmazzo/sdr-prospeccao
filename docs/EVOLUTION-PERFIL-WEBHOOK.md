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
