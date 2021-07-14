#!/bin/bash

# Route required for communicating with secondaries through VPN
/sbin/ip route add 10.8.0.0/24 via 172.16.7.2
/sbin/ip route add 239.1.2.0/24 via 172.16.7.2

# Fix UDP TTL which sometimes is one, causing packets intended for VPN clients to be dropped at the VPN server
# TODO remove this workaround once the problem has been solved at its root
iptables -t mangle -A OUTPUT -p udp -j TTL --ttl-set 64

host=dbmaster; port=3306; n=120; i=0; while ! (echo > /dev/tcp/$host/$port) 2> /dev/null; do [[ $i -eq $n ]] && >&2 echo "$host:$port not up after $n seconds, exiting" && exit 1; echo "waiting for $host:$port to come up"; sleep 1; i=$((i+1)); done

# Manage credentials
envsubst < /etc/powerdns/pdns.conf.var > /etc/powerdns/pdns.conf

exec pdns_server --daemon=no
