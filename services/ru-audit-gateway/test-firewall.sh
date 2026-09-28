#!/usr/bin/env bash
# Only a disposable container namespace is changed. Never touches host rules.
set -euo pipefail
cd "$(dirname "$0")"
docker build -t pepper-ru-audit-gateway:test .
name="pepper-firewall-test-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; docker network rm "$name-net" >/dev/null 2>&1 || true' EXIT
# Compose uses an embedded DNS resolver with output DNAT. A default-bridge-only
# test misses a filter that accidentally blocks the rewritten loopback port.
docker network create "$name-net" >/dev/null
docker run -d --name "$name" --network "$name-net" --cap-drop ALL --cap-add NET_ADMIN --cap-add SETUID --cap-add SETGID --cap-add SETPCAP \
  -e DENY_CIDRS=1.1.1.1/32 pepper-ru-audit-gateway:test sleep 120 >/dev/null
# Readiness means rules exist, not merely that Docker returned a container ID.
for attempt in $(seq 1 30); do
 if docker exec --user 0 "$name" nft list table inet pepper_audit >/dev/null 2>&1; then break; fi
 sleep .2
done
docker exec --user 10001:10001 "$name" sh -ec '
  getent ahostsv4 example.com >/dev/null
  for url in http://127.0.0.1/ http://169.254.169.254/ http://10.0.0.1/ http://1.1.1.1/ http://8.8.8.8:81/ "http://[::1]/"; do
    if curl --noproxy "*" --connect-timeout 2 --max-time 3 "$url" >/dev/null 2>&1; then
      echo "FAIL firewall allowed $url" >&2; exit 1
    fi
  done
  if nft list ruleset >/dev/null 2>&1; then echo "FAIL capabilities retained" >&2; exit 1; fi
'
# A connection refusal alone is NOT evidence of a firewall. Require actual
# packet counters on private, infrastructure and default-port reject rules.
rules="$(docker exec --user 0 "$name" nft list table inet pepper_audit)"
for match in 'ip daddr @denied4' 'ip daddr @infrastructure4' '^[[:space:]]*counter'; do
 if ! echo "$rules" | grep "$match" | grep -Eq 'counter packets [1-9][0-9]* '; then
   echo "FAIL no observed filter hit: $match" >&2; exit 1
 fi
done
echo "PASS embedded DNS; real nftables reject counters; private, infrastructure, ports; service cannot change filter"
