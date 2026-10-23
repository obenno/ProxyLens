#!/bin/bash
set -euo pipefail
if [[ "${1:-}" == healthcheck ]]; then
  exec 3<>/dev/tcp/127.0.0.1/9000
  printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
  read -r -t 3 status <&3
  [[ "$status" == *" 200 "* ]]
  exit
fi
# Keycloak has no generic *_FILE support. Export only inside the container;
# values never appear in Compose interpolation, command arguments, or logs.
export KC_DB_PASSWORD="$(</run/secrets/keycloak_db_password)"
export KC_BOOTSTRAP_ADMIN_PASSWORD="$(</run/secrets/keycloak_admin_password)"
export PROXYLENS_CLIENT_SECRET="$(</run/secrets/keycloak_client_secret)"
[[ -n "$KC_DB_PASSWORD" && -n "$KC_BOOTSTRAP_ADMIN_PASSWORD" && -n "$PROXYLENS_CLIENT_SECRET" ]]
exec /opt/keycloak/bin/kc.sh "$@"
