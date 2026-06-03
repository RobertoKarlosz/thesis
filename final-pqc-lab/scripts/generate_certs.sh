#!/bin/bash
# TLS server authentication uses classical ECDSA P-256.
# PQC is the KEY EXCHANGE (KEM) algorithm negotiated during the TLS handshake.
set -euo pipefail

PQC_ALG="${PQC_ALG:-mlkem768}"
CERT_DIR="${CERT_DIR:-./certs}"
DAYS=3650
CURVE="prime256v1"

echo "==> Certificate generation"
echo "    TLS KEM (key exchange) : ${PQC_ALG}"
echo "    Cert signature alg     : ECDSA P-256"
echo "    Output dir             : ${CERT_DIR}"

mkdir -p "${CERT_DIR}"
rm -f "${CERT_DIR}"/*.key "${CERT_DIR}"/*.crt "${CERT_DIR}"/*.csr "${CERT_DIR}"/*.srl

openssl ecparam -name "${CURVE}" -genkey -noout -out "${CERT_DIR}/ca.key"
openssl req -new -x509 -days "${DAYS}" \
    -key "${CERT_DIR}/ca.key" -out "${CERT_DIR}/ca.crt" \
    -subj "/CN=PQC-IoT-Lab-CA/O=PQC-Lab/C=US"

openssl ecparam -name "${CURVE}" -genkey -noout -out "${CERT_DIR}/server.key"
openssl req -new \
    -key "${CERT_DIR}/server.key" -out "${CERT_DIR}/server.csr" \
    -subj "/CN=mosquitto/O=PQC-Lab/C=US"

openssl x509 -req -days "${DAYS}" \
    -in "${CERT_DIR}/server.csr" \
    -CA "${CERT_DIR}/ca.crt" -CAkey "${CERT_DIR}/ca.key" -CAcreateserial \
    -out "${CERT_DIR}/server.crt" \
    -extfile <(printf "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1")

chmod 644 "${CERT_DIR}"/*.key "${CERT_DIR}"/*.crt 2>/dev/null || true

echo ""
echo "==> Certificate sizes:"
for f in "${CERT_DIR}/ca.key" "${CERT_DIR}/ca.crt" "${CERT_DIR}/server.key" "${CERT_DIR}/server.crt"; do
    [ -f "$f" ] && printf "    %-15s %s bytes\n" "$(basename "$f")" "$(wc -c < "$f")"
done
openssl x509 -in "${CERT_DIR}/ca.crt" -noout -subject -issuer -dates
ls -lh "${CERT_DIR}/"
