#!/bin/bash
# Parametric PQC experiment runner.
# Iterates algorithm × CPU combinations, waits DURATION seconds each,
# then triggers a Prometheus TSDB snapshot.
set -euo pipefail

ALGORITHMS=("mlkem768" "bikel1" "x25519")
CPU_LIMITS=("0.1" "0.25" "0.5" "1.0")
DURATION="${DURATION:-180}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
RESULTS_DIR="${RESULTS_DIR:-./experiment-results}"

mkdir -p "${RESULTS_DIR}"
COMPOSE_CMD="docker compose"
command -v "docker" >/dev/null && docker compose version >/dev/null 2>&1 || COMPOSE_CMD="docker-compose"

echo "=== PQC Experiment Runner ==="
LOG="${RESULTS_DIR}/experiment_$(date +%Y%m%d_%H%M%S).log"
echo "Started: $(date)" > "${LOG}"

for ALG in "${ALGORITHMS[@]}"; do
    for CPU in "${CPU_LIMITS[@]}"; do
        RUN_ID="${ALG}_cpu${CPU}_$(date +%H%M%S)"
        echo "=== ALG=${ALG} CPU=${CPU} ==="
        echo "--- ALG=${ALG} CPU=${CPU} $(date)" >> "${LOG}"

        PQC_ALG="${ALG}" CERT_DIR="./certs" bash scripts/generate_certs.sh 2>&1 | tee -a "${LOG}" || true

        PQC_ALG="${ALG}" NODE_CPUS="${CPU}" PROXY_CPUS="${CPU}" \
            ${COMPOSE_CMD} up -d --force-recreate 2>&1 | tee -a "${LOG}"

        echo "--> Waiting ${DURATION}s ..."
        sleep "${DURATION}"

        SNAP=$(curl -sf -XPOST "${PROMETHEUS_URL}/api/v1/admin/tsdb/snapshot" 2>/dev/null || echo '{}')
        echo "    Snapshot: ${SNAP}" >> "${LOG}"

        python3 -c "
import json
print(json.dumps({'algorithm':'${ALG}','cpu':'${CPU}','duration':${DURATION},'run_id':'${RUN_ID}'},indent=2))
" > "${RESULTS_DIR}/${RUN_ID}.json"

        echo "=== Done: ALG=${ALG} CPU=${CPU} ==="
    done
done

${COMPOSE_CMD} down
echo "All experiments complete. Results: ${RESULTS_DIR}/"
