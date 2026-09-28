#!/bin/sh
# Certbot deploy hook, installed only on the designated VPS.
set -eu
[ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/lts.itsalt.ru ] || exit 0
base=/srv/pepper-ru-audit-gateway
install -o root -g 10001 -m 0640 "$RENEWED_LINEAGE/fullchain.pem" "$base/secrets/tls.crt.new"
install -o root -g 10001 -m 0640 "$RENEWED_LINEAGE/privkey.pem" "$base/secrets/tls.key.new"
mv "$base/secrets/tls.crt.new" "$base/secrets/tls.crt"
mv "$base/secrets/tls.key.new" "$base/secrets/tls.key"
docker compose --project-directory "$base/current" --env-file "$base/gateway.env" \
  -p pepper-ru-audit-gateway -f "$base/current/compose.yaml" \
  -f "$base/current/deploy/compose.vps.yaml" restart gateway
