#!/usr/bin/env bash
# Atualiza nome / foto / status do perfil WhatsApp via Evolution 2.3.7
# SEM reiniciar nem desconectar a instância.
# VOCÊ executa este script na VPS. O agente NÃO deve rodá-lo.
#
# Uso:
#   export EVOLUTION_BASE_URL="https://sua-evolution"
#   export EVOLUTION_API_KEY="..."
#   export EVOLUTION_INSTANCE="poli"
#   export PROFILE_NAME="NomeExibido"          # opcional; default $AGENT_NAME ou Edu
#   export PROFILE_PICTURE_URL="https://..."   # HTTPS público JPG/PNG
#   export PROFILE_STATUS="Consultoria de matrícula · Faveni"
#   ./scripts/evolution_profile.sh show
#   ./scripts/evolution_profile.sh apply-name
#   ./scripts/evolution_profile.sh apply-picture
#   ./scripts/evolution_profile.sh apply-status
#
# Dependências: curl, jq

set -euo pipefail

: "${EVOLUTION_BASE_URL:?defina EVOLUTION_BASE_URL}"
: "${EVOLUTION_API_KEY:?defina EVOLUTION_API_KEY}"
: "${EVOLUTION_INSTANCE:?defina EVOLUTION_INSTANCE}"

BASE="${EVOLUTION_BASE_URL%/}"
INST="$EVOLUTION_INSTANCE"
HDR=(-H "apikey: ${EVOLUTION_API_KEY}" -H "Content-Type: application/json")
PROFILE_NAME="${PROFILE_NAME:-${AGENT_NAME:-Edu}}"
PROFILE_STATUS="${PROFILE_STATUS:-Consultoria de matrícula · Faveni}"

echo "== instance: ${INST} @ ${BASE} =="

cmd_show() {
  echo "== tentativa de leitura (endpoints variam; 404 é ok) =="
  for path in \
    "chat/fetchProfile/${INST}" \
    "chat/fetchBusinessProfile/${INST}" \
    "instance/fetchInstances"
  do
    echo "--- GET /${path} ---"
    code=$(curl -sS -o /tmp/edu-profile-show.json -w "%{http_code}" \
      "${BASE}/${path}" "${HDR[@]}" || true)
    echo "HTTP ${code}"
    if [[ -f /tmp/edu-profile-show.json ]]; then
      jq . /tmp/edu-profile-show.json 2>/dev/null || cat /tmp/edu-profile-show.json
    fi
    echo
  done
  echo "Nome pretendido (PROFILE_NAME): ${PROFILE_NAME}"
  echo "Status pretendido (PROFILE_STATUS): ${PROFILE_STATUS}"
  echo "Foto pretendida (PROFILE_PICTURE_URL): ${PROFILE_PICTURE_URL:-"(não definido)"}"
}

cmd_apply_name() {
  BODY=$(jq -n --arg name "$PROFILE_NAME" '{name: $name}')
  echo "== POST /chat/updateProfileName/${INST} =="
  echo "$BODY" | jq .
  curl -sS -X POST "${BASE}/chat/updateProfileName/${INST}" "${HDR[@]}" -d "$BODY" | jq .
  echo
  echo "Pronto. Sem restart/logout. Confira o nome no WhatsApp."
}

cmd_apply_picture() {
  : "${PROFILE_PICTURE_URL:?defina PROFILE_PICTURE_URL (HTTPS público)}"
  BODY=$(jq -n --arg picture "$PROFILE_PICTURE_URL" '{picture: $picture}')
  echo "== POST /chat/updateProfilePicture/${INST} =="
  echo "$BODY" | jq .
  curl -sS -X POST "${BASE}/chat/updateProfilePicture/${INST}" "${HDR[@]}" -d "$BODY" | jq .
  echo
  echo "Pronto. Sem restart/logout. Confira a foto no WhatsApp."
}

cmd_apply_status() {
  BODY=$(jq -n --arg status "$PROFILE_STATUS" '{status: $status}')
  echo "== POST /chat/updateProfileStatus/${INST} =="
  echo "$BODY" | jq .
  curl -sS -X POST "${BASE}/chat/updateProfileStatus/${INST}" "${HDR[@]}" -d "$BODY" | jq .
  echo
  echo "Pronto. Sem restart/logout."
}

case "${1:-}" in
  show) cmd_show ;;
  apply-name) cmd_apply_name ;;
  apply-picture) cmd_apply_picture ;;
  apply-status) cmd_apply_status ;;
  *)
    echo "Uso: $0 {show|apply-name|apply-picture|apply-status}" >&2
    exit 1
    ;;
esac
