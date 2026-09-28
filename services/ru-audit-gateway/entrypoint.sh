#!/bin/sh
set -eu
: "${DENY_CIDRS:?Include all gateway public addresses and service infrastructure CIDRs}"
# Never flush host rules. Container must NOT use host networking or be privileged.
nft list table inet pepper_audit >/dev/null 2>&1 && nft delete table inet pepper_audit
nft -f /etc/gateway-firewall.nft
for cidr in $(echo "$DENY_CIDRS" | tr ',' ' '); do
 case "$cidr" in *:*) family=6;; *) family=4;; esac
 nft add element inet pepper_audit "infrastructure$family" "{ $cidr }"
done
# Permit only the container's configured resolver, on DNS ports only.
for resolver in $(awk '$1=="nameserver" {print $2}' /etc/resolv.conf); do
 case "$resolver" in *:*) family=6;; *) family=4;; esac
 nft add element inet pepper_audit "dns$family" "{ $resolver }"
done
# No capabilities (including NET_ADMIN) remain in the service process.
exec setpriv --reuid=10001 --regid=10001 --clear-groups --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs "$@"
