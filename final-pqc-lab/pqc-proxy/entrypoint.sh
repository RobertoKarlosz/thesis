#!/bin/bash
set -euo pipefail

PQC_ALG="${PQC_ALG:-mlkem768}"
MOSQUITTO_HOST="${MOSQUITTO_HOST:-mosquitto}"
MOSQUITTO_PORT="${MOSQUITTO_PORT:-8883}"
METRICS_DIR="/var/lib/prometheus"
PROM_FILE="${METRICS_DIR}/handshake_ms.prom"
METRICS_PORT="${METRICS_PORT:-9101}"

mkdir -p "${METRICS_DIR}"

echo "==> PQC proxy starting. Algorithm: ${PQC_ALG}"

envsubst '${PQC_ALG}' \
    < /etc/stunnel/stunnel.conf.template \
    > /etc/stunnel/stunnel.conf

echo "==> Generated stunnel config:"
cat /etc/stunnel/stunnel.conf

MAX_WAIT=60
WAITED=0
until openssl s_client \
       -connect "${MOSQUITTO_HOST}:${MOSQUITTO_PORT}" \
       -CAfile /certs/ca.crt \
       -groups "${PQC_ALG}" \
       -tls1_3 </dev/null >/dev/null 2>&1; do
    if [ "${WAITED}" -ge "${MAX_WAIT}" ]; then
        echo "WARNING: mosquitto not reachable after ${MAX_WAIT}s, continuing anyway"
        break
    fi
    echo "==> Waiting for mosquitto:${MOSQUITTO_PORT} ... (${WAITED}s)"
    sleep 2
    WAITED=$((WAITED + 2))
done

echo "==> Measuring PQC handshake latency for algorithm: ${PQC_ALG}"
TOTAL_MS=0
SAMPLES=0
for i in 1 2 3; do
    START_NS=$(date +%s%N)
    openssl s_client \
        -connect "${MOSQUITTO_HOST}:${MOSQUITTO_PORT}" \
        -CAfile /certs/ca.crt \
        -groups "${PQC_ALG}" \
        -tls1_3 -brief \
        </dev/null 2>&1 | grep -E "^(Connecting|CONNECTION)" || true
    END_NS=$(date +%s%N)
    ELAPSED_MS=$(( (END_NS - START_NS) / 1000000 ))
    echo "  Attempt ${i}: ${ELAPSED_MS} ms"
    TOTAL_MS=$((TOTAL_MS + ELAPSED_MS))
    SAMPLES=$((SAMPLES + 1))
done

AVG_MS=$((TOTAL_MS / SAMPLES))
echo "==> Average handshake latency: ${AVG_MS} ms"

cat > "${PROM_FILE}" <<PROMEOF
# HELP handshake_latency_ms PQC TLS handshake latency in milliseconds
# TYPE handshake_latency_ms gauge
handshake_latency_ms{algorithm="${PQC_ALG}",proxy="${HOSTNAME}"} ${AVG_MS}
PROMEOF

cat > /tmp/metrics_server.py <<'PYEOF'
import http.server, sys

prom_file = sys.argv[1]
port = int(sys.argv[2])

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        if self.path in ('/', '/metrics'):
            try:
                body = open(prom_file).read().encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; version=0.0.4')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

http.server.HTTPServer(('0.0.0.0', port), Handler).serve_forever()
PYEOF

python3 /tmp/metrics_server.py "${PROM_FILE}" "${METRICS_PORT}" &
echo "==> Metrics HTTP server listening on :${METRICS_PORT}"

STUNNEL_BIN=$(command -v stunnel || command -v stunnel4 || echo /usr/bin/stunnel)
echo "==> Starting stunnel (${STUNNEL_BIN})"
exec "${STUNNEL_BIN}" /etc/stunnel/stunnel.conf
