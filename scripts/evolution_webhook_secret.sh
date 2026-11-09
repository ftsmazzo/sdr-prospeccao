#!/usr/bin/env bash
# Configura X-Webhook-Secret no webhook da Evolution SEM reiniciar/logout da instance.
# Formato do body: Evolution 2.x (ex. 2.3.7) — objeto aninhado "webhook" com byEvents/base64.
# VOCÊ executa este script. O agente NÃO deve rodá-lo.
#
# Uso:
#   export EVOLUTION_BASE_URL="https://poli2-evolution-api.kxryyk.easypanel.host"
#   export EVOLUTION_API_KEY="..."
#   export EVOLUTION_INSTANCE="poli"
#   export WEBHOOK_SECRET="seu-secret-longo-aleatorio"
#   ./scripts/evolution_webhook_secret.sh show
#   ./scripts/evolution_webhook_secret.sh apply-header
#   ./scripts/evolution_webhook_secret.sh apply-path
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
BACKUP_DIR="${BACKUP_DIR:-/tmp}"
BACKUP_FILE="${BACKUP_FILE:-${BACKUP_DIR}/edu-webhook-backup-${INST}.json}"

find_webhook() {
  curl -sS "${BASE}/webhook/find/${INST}" "${HDR[@]}"
}

_backup_path_for_show() {
  if [[ -f "$BACKUP_FILE" ]]; then
    local stamp
    stamp=$(date +%Y%m%d-%H%M%S)
    local alt="${BACKUP_DIR}/edu-webhook-backup-${INST}-${stamp}.json"
    echo "AVISO: backup já existe em $BACKUP_FILE — salvando consulta atual em $alt" >&2
    echo "$alt"
  else
    echo "$BACKUP_FILE"
  fi
}

cmd_show() {
  echo "== webhook atual (${INST}) =="
  local out
  out="$(_backup_path_for_show)"
  find_webhook | tee "$out" | jq .
  echo
  echo "Snapshot salvo em: $out"
  if [[ "$out" != "$BACKUP_FILE" ]]; then
    echo "Undo continua usando o backup principal: $BACKUP_FILE"
    echo "Para desfazer a partir deste snapshot: BACKUP_FILE=$out $0 undo"
  fi
}

# Extrai campos do find (formatos variam; prioriza aninhado webhook.*)
_parse() {
  local raw file="${1:-$BACKUP_FILE}"
  raw="$(cat "$file")"
  URL=$(echo "$raw" | jq -r '
    .webhook.url // .url // .webhook.webhook.url // empty
  ')
  ENABLED=$(echo "$raw" | jq -r '
    .webhook.enabled // .enabled // .webhook.webhook.enabled // true
  ')
  BY_EVENTS=$(echo "$raw" | jq -r '
    .webhook.byEvents // .webhook.webhookByEvents // .byEvents // .webhookByEvents // false
  ')
  BASE64=$(echo "$raw" | jq -r '
    .webhook.base64 // .webhook.webhookBase64 // .base64 // .webhookBase64 // false
  ')
  EVENTS=$(echo "$raw" | jq -c '
    .webhook.events // .events // .webhook.webhook.events // ["MESSAGES_UPSERT"]
  ')
  OLD_HEADERS=$(echo "$raw" | jq -c '
    .webhook.headers // .headers // .webhook.webhook.headers // {}
  ')
}

_set_body() {
  # Evolution 2.3.x: { "webhook": { enabled, url, events, headers, byEvents, base64 } }
  jq -n \
    --arg url "$URL" \
    --argjson enabled "$ENABLED" \
    --argjson byEvents "$BY_EVENTS" \
    --argjson base64 "$BASE64" \
    --argjson events "$EVENTS" \
    --argjson headers "$HEADERS" \
    '{
      webhook: {
        enabled: $enabled,
        url: $url,
        events: $events,
        headers: $headers,
        byEvents: $byEvents,
        base64: $base64
      }
    }'
}

cmd_apply_header() {
  : "${WEBHOOK_SECRET:?defina WEBHOOK_SECRET}"
  if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Sem backup principal. Rode: $0 show (primeira vez cria $BACKUP_FILE)" >&2
    exit 1
  fi
  _parse "$BACKUP_FILE"
  if [[ -z "$URL" ]]; then
    echo "Não consegui ler a URL do webhook no backup. Rode: $0 show" >&2
    exit 1
  fi
  echo "URL atual: $URL"
  echo "Events: $EVENTS"
  HEADERS=$(echo "$OLD_HEADERS" | jq --arg s "$WEBHOOK_SECRET" '. + {"X-Webhook-Secret": $s}')
  BODY=$(_set_body)
  echo "== POST /webhook/set/${INST} (header, body aninhado webhook) =="
  echo "$BODY" | jq .
  curl -sS -X POST "${BASE}/webhook/set/${INST}" "${HDR[@]}" -d "$BODY" | jq .
  echo
  echo "Pronto. No Edu: WEBHOOK_SECRET_ENFORCE=false até confirmar logs; depois true."
}

cmd_apply_path() {
  : "${WEBHOOK_SECRET:?defina WEBHOOK_SECRET}"
  if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Sem backup principal. Rode: $0 show" >&2
    exit 1
  fi
  _parse "$BACKUP_FILE"
  if [[ -z "$URL" ]]; then
    echo "Não consegui ler a URL do webhook no backup. Rode: $0 show" >&2
    exit 1
  fi
  BASE_URL=$(echo "$URL" | sed -E 's#/webhooks/evolution(/[^/?]*)?$#/webhooks/evolution#')
  URL="${BASE_URL%/}/${WEBHOOK_SECRET}"
  HEADERS=$(echo "$OLD_HEADERS" | jq '.')
  echo "URL nova (path secret): $URL"
  BODY=$(_set_body)
  echo "== POST /webhook/set/${INST} (path secret) =="
  echo "$BODY" | jq .
  curl -sS -X POST "${BASE}/webhook/set/${INST}" "${HDR[@]}" -d "$BODY" | jq .
}

cmd_undo() {
  if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Sem backup em $BACKUP_FILE — rode show antes." >&2
    exit 1
  fi
  _parse "$BACKUP_FILE"
  HEADERS="$OLD_HEADERS"
  BODY=$(_set_body)
  echo "== undo POST /webhook/set/${INST} =="
  echo "$BODY" | jq .
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
