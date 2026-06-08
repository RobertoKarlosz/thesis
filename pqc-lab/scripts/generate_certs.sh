#!/bin/bash
# generate_certs.sh – ECDSA P-256 CA és szerver tanúsítványok generálása a PQC IoT Lab számára.
#
# A TLS szerver hitelesítés klasszikus ECDSA P-256 algoritmust használ (amelyet az
# OpenSSL TLS biztonsági szint ellenőrzések mindenütt támogatnak). A kísérlet PQC
# vonatkozása a TLS kézfogás során a stunnel "curves" beállításán keresztül egyeztetett
# KULCSCSERE algoritmus (KEM) – nem a tanúsítvány aláírási algoritmusa.
set -euo pipefail

PQC_ALG="${PQC_ALG:-mlkem768}"   # csak tájékoztató; a tanúsítványok mindig ECDSA alapúak
CERT_DIR="${CERT_DIR:-./certs}"
DAYS=3650
CURVE="prime256v1"               # P-256

echo "==> Certificate generation"
echo "    TLS KEM (key exchange) : ${PQC_ALG}  (configured in stunnel, not in certs)"
echo "    Cert signature alg     : ECDSA P-256"
echo "    Output dir             : ${CERT_DIR}"

mkdir -p "${CERT_DIR}"
rm -f "${CERT_DIR}"/*.key "${CERT_DIR}"/*.crt "${CERT_DIR}"/*.csr "${CERT_DIR}"/*.srl

echo "==> Generating CA key and self-signed certificate"
openssl ecparam -name "${CURVE}" -genkey -noout -out "${CERT_DIR}/ca.key"
openssl req -new -x509 -days "${DAYS}" \
    -key "${CERT_DIR}/ca.key" \
    -out "${CERT_DIR}/ca.crt" \
    -subj "/CN=PQC-IoT-Lab-CA/O=PQC-Lab/C=US"

echo "==> Generating server key and CSR"
openssl ecparam -name "${CURVE}" -genkey -noout -out "${CERT_DIR}/server.key"
openssl req -new \
    -key "${CERT_DIR}/server.key" \
    -out "${CERT_DIR}/server.csr" \
    -subj "/CN=mosquitto/O=PQC-Lab/C=US"

echo "==> Signing server certificate with CA"
openssl x509 -req -days "${DAYS}" \
    -in "${CERT_DIR}/server.csr" \
    -CA "${CERT_DIR}/ca.crt" \
    -CAkey "${CERT_DIR}/ca.key" \
    -CAcreateserial \
    -out "${CERT_DIR}/server.crt" \
    -extfile <(printf "subjectAltName=DNS:mosquitto,DNS:localhost,IP:127.0.0.1")

echo ""
echo "==> Certificate sizes (bytes):"
for f in "${CERT_DIR}/ca.key" "${CERT_DIR}/ca.crt" "${CERT_DIR}/server.key" "${CERT_DIR}/server.crt"; do
    [ -f "$f" ] && printf "    %-15s %s bytes\n" "$(basename "$f")" "$(wc -c < "$f")"
done

echo ""
echo "==> CA certificate info:"
openssl x509 -in "${CERT_DIR}/ca.crt" -noout -subject -issuer -dates

# A tanúsítványok olvashatóvá tétele a nem root felhasználóként futó konténer folyamatok számára
chmod 644 "${CERT_DIR}"/*.key "${CERT_DIR}"/*.crt 2>/dev/null || true

echo ""
echo "==> Certificates written to ${CERT_DIR}/"
ls -lh "${CERT_DIR}/"
