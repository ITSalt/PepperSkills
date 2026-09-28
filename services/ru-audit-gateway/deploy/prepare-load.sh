#!/bin/sh
# Run with sudo on the designated VPS. Alters only the disposable test project.
set -eu
base=/srv/pepper-ru-audit-gateway
install -d -o root -g 10001 -m 0750 "$base/load-secrets"
install -o root -g 10001 -m 0640 "$base/secrets/tls.crt" "$base/load-secrets/tls.crt"
install -o root -g 10001 -m 0640 "$base/secrets/tls.key" "$base/load-secrets/tls.key"
umask 027
if [ ! -s "$base/load-secrets/hmac" ]; then
 openssl rand -hex 32 > "$base/load-secrets/hmac"
fi
chown root:10001 "$base/load-secrets/hmac"
chmod 0640 "$base/load-secrets/hmac"
cd "$base/current/deploy"
docker compose -p pepper-audit-load -f compose.load.yaml up -d --pull never gateway fixture
fixture=$(docker compose -p pepper-audit-load -f compose.load.yaml ps -q fixture)
gateway=$(docker compose -p pepper-audit-load -f compose.load.yaml ps -q gateway)
# This owned public address exists ONLY inside the fixture namespace. Its real
# server receives no packets. No public routes or host firewall rules are changed.
nsenter -t "$(docker inspect -f '{{.State.Pid}}' "$fixture")" -n ip addr replace 82.202.140.54/32 dev lo
nsenter -t "$(docker inspect -f '{{.State.Pid}}' "$gateway")" -n ip route replace 82.202.140.54/32 via 10.240.82.3
# Prove namespace isolation and native filter before the load starts.
nsenter -t "$(docker inspect -f '{{.State.Pid}}' "$gateway")" -n ip route get 82.202.140.54
docker exec "$gateway" nft list table inet pepper_audit >/dev/null
printf 'Isolated load fixture ready\n'
