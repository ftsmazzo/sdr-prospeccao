#!/usr/bin/env bash
# Configura X-Webhook-Secret no webhook da Evolution SEM reiniciar/logout da instance.
# VOCÊ executa este script. O agente NÃO deve rodá-lo.
#
# Uso:
#   export EVOLUTION_BASE_URL="https://poli2-evolution-api.kxryyk.easypanel.host"
#   export EVOLUTION_API_KEY="..."
#   export EVOLUTION_INSTANCE="poli"
#   export WEBHOOK_SECRET="seu-secret-longo-aleatorio"
#   ./scripts/evolution_webhook_secret.sh show
#   ./scripts/evolution_webhook_secret.sh apply-header
#   ./scripts/evolution_webhook_secret.sh apply-path   # plano B se headers não forem aceitos
#   ./scripts/evolution_webhook_secret.sh undo
#
# Dependências: curl, jq

set -euo pipefail

: "${EVOLUTION_BASE_URL:?defina EVOLUTION_BASE_URL}"
: "${EVOLUTION_API_KEY:?defina EVOLUTION_API_KEY}"
: "${EVOLUTION_INSTANCE:?defina EVOLUTION_INSTANCE}"

BASE="${EVOLUTION_BASE_URL%/}"
INST="$EVOLUTION_INSTANCE"
HDR=(-H "apikey: ${EVOLUTION_API_KEY}" -H "Content-Type: application/json")
BACKUP_FILE="${BACKUP_FILE:-/tmp/edu-webhook-backup-${INST}.json}"

find_webhook() {
  # Evolution v2 típico
  curl -sS "${BASE}/webhook/find/${INST}" "${HDR[@]}"
}

cmd_show() {
  echo "== webhook atual (${INST}) =="
  find_webhook | tee "$BACKUP_FILE" | jq .
  echo
  echo "Backup salvo em: $BACKUP_FILE"
}

# Extrai campos do find (formatos variam um pouco entre versões)
_parse() {
  local raw
  raw="$(cat "$BACKUP_FILE")"
  URL=$(echo "$raw" | jq -r '.url // .webhook.url // .webhook.webhook.url // empty')
  ENABLED=$(echo "$raw" | jq -r '.enabled // .webhook.enabled // .webhook.webhook.enabled // true')
  BY_EVENTS=$(echo "$raw" | jq -r '.webhookByEvents // .byEvents // .webhook.webhookByEvents // .webhook.byEvents // false')
  BASE64=$(echo "$raw" | jq -r '.webhookBase64 // .base64 // .webhook.webhookBase64 // .webhook.base64 // false')
  EVENTS=$(echo "$raw" | jq -c '.events // .webhook.events // .webhook.webhook.events // ["MESSAGES_UPSERT"]')
  OLD_HEADERS=$(echo "$raw" | jq -c '.headers // .webhook.headers // .webhook.webhook.headers // {}')
}

cmd_apply_header() {
  : "${WEBHOOK_SECRET:?defina WEBHOOK_SECRET}"
  if [[ ! -f "$BACKUP_FILE" ]]; then
    cmd_show >/dev/null
  fi
  _parse
  if [[ -z "$URL" ]]; then
    echo "Não consegui ler a URL do webhook. Rode: $0 show" >&2
    exit 1
  fi
  echo "URL atual: $URL"
  echo "Events: $EVENTS"
  NEW_HEADERS=$(echo "$OLD_HEADERS" | jq --arg s "$WEBHOOK_SECRET" '. + {"X-Webhook-Secret": $s}')
  BODY=$(jq -n \
    --arg url "$URL" \
    --argjson enabled "$ENABLED" \
    --argjson byEvents "$BY_EVENTS" \
    --argjson base64 "$BASE64" \
    --argjson events "$EVENTS" \
    --argjson headers "$NEW_HEADERS" \
    '{enabled:$enabled, url:$url, webhookByEvents:$byEvents, webhookBase64:$base64, events:$events, headers:$headers}')
  echo "== setWebhook (header) =="
  curl -sS -X POST "${BASE}/webhook/set/${INST}" "${HDR[@]}" -d "$BODY" | jq .
  echo
  echo "Pronto. No Edu: WEBHOOK_SECRET_ENFORCE=false até confirmar logs; depois true."
}

cmd_apply_path() {
  : "${WEBHOOK_SECRET:?defina WEBHOOK_SECRET}"
  if [[ ! -f "$BACKUP_FILE" ]]; then
    cmd_show >/dev/null
  fi
  _parse
  if [[ -z "$URL" ]]; then
    echo "Não consegui ler a URL do webhook. Rode: $0 show" >&2
    exit 1
  fi
  # normaliza para .../webhooks/evolution/<secret>
  BASE_URL=$(echo "$URL" | sed -E 's#/webhooks/evolution(/[^/?]*)?$#/webhooks/evolution#')
  NEW_URL="${BASE_URL%/}/${WEBHOOK_SECRET}"
  echo "URL antiga: $URL"
  echo "URL nova:   $NEW_URL"
  BODY=$(jq -n \
    --arg url "$NEW_URL" \
    --argjson enabled "$ENABLED" \
    --argjson byEvents "$BY_EVENTS" \
    --argjson base64 "$BASE64" \
    --argjson events "$EVENTS" \
    '{enabled:$enabled, url:$url, webhookByEvents:$byEvents, webhookBase64:$base64, events:$events}')
  echo "== setWebhook (path secret) =="
  curl -sS -X POST "${BASE}/webhook/set/${INST}" "${HDR[@]}" -d "$BODY" | jq .
}

cmd_undo() {
  if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Sem backup em $BACKUP_FILE — rode show antes." >&2
    exit 1
  fi
  _parse
  BODY=$(jq -n \
    --arg url "$URL" \
    --argjson enabled "$ENABLED" \
    --argjson byEvents "$BY_EVENTS" \
    --argjson base64 "$BASE64" \
    --argjson events "$EVENTS" \
    --argjson headers "$OLD_HEADERS" \
    '{enabled:$enabled, url:$url, webhookByEvents:$byEvents, webhookBase64:$base64, events:$events, headers:$headers}')
  echo "== undo setWebhook =="
  curl -sS -X POST "${BASE}/webhook/set/${INST}" "${HDR[@]}" -d "$BODY" | jq .
}

case "${1:-}" in
  show) cmd_show ;;
  apply-header) cmd_apply_header ;;
  apply-path) cmd_apply_path ;;
  undo) cmd_undo ;;
  *)
    echo "Uso: $0 {show|apply-header|apply-path|undo}" >&2
    exit 1
    ;;
esac
