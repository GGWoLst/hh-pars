#!/bin/sh
set -e

# Ограничение исходящей полосы контейнера (нужен cap_add: NET_ADMIN).
# Задаётся через BANDWIDTH_LIMIT_MBIT, по умолчанию не применяется.
if [ -n "$BANDWIDTH_LIMIT_MBIT" ]; then
    tc qdisc replace dev eth0 root tbf rate "${BANDWIDTH_LIMIT_MBIT}mbit" burst 1mbit latency 50ms
fi

exec "$@"
