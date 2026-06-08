#!/bin/bash
set -euo pipefail

PQC_ALG="${PQC_ALG:-mlkem768}"

echo "==> Mosquitto+stunnel entrypoint. PQC_ALG=${PQC_ALG}"

mkdir -p /run/stunnel /var/run/mosquitto /var/lib/mosquitto

# PQC_ALG behelyettesítése a stunnel szerver konfigurációjába
envsubst '${PQC_ALG}' \
    < /etc/stunnel/stunnel-server.conf.template \
    > /etc/stunnel/stunnel-server.conf

echo "==> stunnel server config:"
cat /etc/stunnel/stunnel-server.conf

# stunnel bináris megkeresése (az apt stunnel4 vagy stunnel névvel telepíti)
STUNNEL_BIN=$(command -v stunnel4 2>/dev/null || command -v stunnel || echo /usr/bin/stunnel4)
echo "==> Starting stunnel server (${STUNNEL_BIN})"
"${STUNNEL_BIN}" /etc/stunnel/stunnel-server.conf &
STUNNEL_PID=$!

# Várakozás, amíg a stunnel foglalja a 8883-as portot
for i in $(seq 1 10); do
    ss -tlnp | grep -q ':8883' && break
    echo "  waiting for stunnel to bind 8883... (${i})"
    sleep 1
done

echo "==> Starting mosquitto"
exec /usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf
