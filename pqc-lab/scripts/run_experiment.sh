#!/bin/bash
# run_experiment.sh – Paraméteres PQC kísérletfuttató
# Használat:
#   ./scripts/run_experiment.sh                                          # összes algoritmus × CPU
#   ./scripts/run_experiment.sh --alg mlkem512                           # egy algoritmus, összes CPU
#   ./scripts/run_experiment.sh --cpu 1.0                                # összes algoritmus, egy CPU
#   ./scripts/run_experiment.sh --alg mlkem512 --cpu 1.0                 # egyetlen futtatás
#   ./scripts/run_experiment.sh --alg mlkem512 --cpu 1.0 --duration 60   # egyetlen futtatás, 60s
#   ALG=mlkem512 CPU=1.0 DURATION=60 ./scripts/run_experiment.sh         # környezeti változó forma (azonos hatás)
set -euo pipefail

# ── Argumentumok feldolgozása ─────────────────────────────────────────────────
_ARG_ALG=""
_ARG_CPU=""
_ARG_DURATION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --alg)      _ARG_ALG="$2";      shift 2 ;;
        --cpu)      _ARG_CPU="$2";      shift 2 ;;
        --duration) _ARG_DURATION="$2"; shift 2 ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            echo "Usage: $0 [--alg <algorithm>] [--cpu <limit>] [--duration <seconds>]" >&2
            exit 1
            ;;
    esac
done

# A parancssori argumentumok felülírják a környezeti változókat
_SELECTED_ALG="${_ARG_ALG:-${ALG:-}}"
_SELECTED_CPU="${_ARG_CPU:-${CPU:-}}"

if [ -n "${_SELECTED_ALG}" ]; then
    ALGORITHMS=("${_SELECTED_ALG}")
else
    ALGORITHMS=("mlkem512" "mlkem768" "mlkem1024" "X25519MLKEM768" "bikel1" "bikel3" "bikel5" "x25519")
fi

if [ -n "${_SELECTED_CPU}" ]; then
    CPU_LIMITS=("${_SELECTED_CPU}")
else
    CPU_LIMITS=("0.026" "0.12" "0.25" "0.5" "1.0")
    # 0.026 ≈ ESP32 (Xtensa LX7 240 MHz, ~57 Passmark)
    # 0.12  ≈ RPi Zero 2W (Cortex-A53 1 GHz, ~220 Passmark)
    # 0.25  ≈ RPi 3B+     (Cortex-A53 1,4 GHz, ~450 Passmark)
    # 0.50  ≈ RPi 4B      (Cortex-A72 1,5 GHz, ~950 Passmark)
    # 1.00  ≈ ipari gateway / Intel Atom szintű eszköz
fi
DURATION="${_ARG_DURATION:-${DURATION:-900}}"   # seconds per run
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
RESULTS_DIR="${RESULTS_DIR:-./experiment-results}"

BAR_WIDTH=40
TOTAL_RUNS=$(( ${#ALGORITHMS[@]} * ${#CPU_LIMITS[@]} ))
RUN_NUM=0

PROM_WARN_FILE=$(mktemp)
PROM_ERR_FILE=$(mktemp)
PROM_LOG_PID=""

count_lines() { wc -l < "$1" 2>/dev/null | xargs; }

# ── Folyamatjelző sáv segédfüggvények ────────────────────────────────────────

# Kitöltött/üres sáv karakterlánc építése: make_bar <kitöltött> <összes> <szélesség>
make_bar() {
    local filled=$(( $1 * $3 / $2 ))
    local rest=$(( $3 - filled ))
    printf '%*s' "$filled" '' | tr ' ' '='
    printf '%*s' "$rest"  '' | tr ' ' '.'
}

# Az összesített konfigurációs folyamatsor kiírása (statikus, nem \r-rel felülírva)
print_config_bar() {
    local current=$1 alg=$2 cpu=$3
    local bar pct
    bar=$(make_bar "$current" "$TOTAL_RUNS" "$BAR_WIDTH")
    pct=$(( current * 100 / TOTAL_RUNS ))
    printf "  Config [%s] %3d%%  %2d/%-2d | %-10s @ CPU=%s\n" \
        "$bar" "$pct" "$current" "$TOTAL_RUNS" "$alg" "$cpu"
}

# Élő idő-folyamatjelző; a Prometheus figyelmeztető/hiba számát is megjeleníti a megosztott fájlokból
sleep_with_progress() {
    local duration=$1 alg=$2 cpu=$3
    local start elapsed bar pct warns errs
    start=$(date +%s)
    while true; do
        elapsed=$(( $(date +%s) - start ))
        [ "$elapsed" -ge "$duration" ] && elapsed=$duration
        bar=$(make_bar "$elapsed" "$duration" "$BAR_WIDTH")
        pct=$(( elapsed * 100 / duration ))
        warns=$(count_lines "${PROM_WARN_FILE}")
        errs=$(count_lines "${PROM_ERR_FILE}")
        printf "\r  Time  [%s] %3d%%  %3ds / %ds  | %-10s @ CPU=%s  [W:%-2s E:%-2s]" \
            "$bar" "$pct" "$elapsed" "$duration" "$alg" "$cpu" "$warns" "$errs"
        [ "$elapsed" -ge "$duration" ] && break
        sleep 1
    done
    printf "\n"
}

# ── Prometheus napló rögzítése ────────────────────────────────────────────────

start_prom_log_capture() {
    local experiment_log=$1
    : > "${PROM_WARN_FILE}"
    : > "${PROM_ERR_FILE}"
    (
        ${COMPOSE_CMD} logs --tail 0 --follow --no-log-prefix prometheus 2>/dev/null | \
        while IFS= read -r line; do
            printf '[prometheus] %s\n' "${line}" >> "${experiment_log}"
            case "${line,,}" in
                *" warn"*|*"warning"*) printf 'w\n' >> "${PROM_WARN_FILE}" ;;
                *" error"*|*"err "*  ) printf 'e\n' >> "${PROM_ERR_FILE}"  ;;
            esac
        done
    ) &
    PROM_LOG_PID=$!
}

stop_prom_log_capture() {
    if [ -n "${PROM_LOG_PID}" ]; then
        kill "${PROM_LOG_PID}" 2>/dev/null || true
        wait "${PROM_LOG_PID}" 2>/dev/null || true
        PROM_LOG_PID=""
    fi
}

cleanup() {
    stop_prom_log_capture
    rm -f "${PROM_WARN_FILE}" "${PROM_ERR_FILE}"
}
trap cleanup EXIT

# ── Inicializálás ────────────────────────────────────────────────────────────

mkdir -p "${RESULTS_DIR}"

COMPOSE_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
fi

echo "=== PQC Experiment Runner ==="
echo "    Algorithms : ${ALGORITHMS[*]}"
echo "    CPU limits : ${CPU_LIMITS[*]}"
echo "    Duration   : ${DURATION}s per run"
echo "    Total runs : ${TOTAL_RUNS}"
echo "    Results    : ${RESULTS_DIR}"
echo ""

EXPERIMENT_LOG="${RESULTS_DIR}/experiment_$(date +%Y%m%d_%H%M%S).log"
echo "Experiment started at $(date)" > "${EXPERIMENT_LOG}"

# ── A megfigyelési stack futásának biztosítása ───────────────────────────────
echo "--> Starting observability stack (prometheus, grafana, node-exporter)"
${COMPOSE_CMD} up -d prometheus grafana node-exporter 2>&1 | tee -a "${EXPERIMENT_LOG}"
echo "--> Waiting for Prometheus to be ready..."
until curl -sf "${PROMETHEUS_URL}/-/healthy" >/dev/null 2>&1; do sleep 2; done
echo "--> Prometheus is ready"
echo ""

# ── Fő ciklus ────────────────────────────────────────────────────────────────

for _ALG in "${ALGORITHMS[@]}"; do
    for _CPU in "${CPU_LIMITS[@]}"; do
        RUN_NUM=$(( RUN_NUM + 1 ))
        RUN_ID="${_ALG}_cpu${_CPU}_$(date +%H%M%S)"

        print_config_bar "$RUN_NUM" "$_ALG" "$_CPU"
        echo "--- Run: ALG=${_ALG} CPU=${_CPU} at $(date)" >> "${EXPERIMENT_LOG}"

        # Tanúsítványok újragenerálása az aktuális algoritmushoz
        echo "--> Generating certificates for ${_ALG}"
        PQC_ALG="${_ALG}" CERT_DIR="./certs" bash scripts/generate_certs.sh 2>&1 | \
            tee -a "${EXPERIMENT_LOG}" || echo "WARNING: cert gen failed, using existing certs"

        # Az összes szolgáltatás elindítása/újralétrehozása az új paraméterekkel
        PQC_ALG="${_ALG}" NODE_CPUS="${_CPU}" PROXY_CPUS="${_CPU}" \
            ${COMPOSE_CMD} up -d --force-recreate \
            mosquitto pqc-proxy-a pqc-proxy-b pqc-proxy-c \
            temperature-sensor-1 temperature-sensor-2 temperature-sensor-3 2>&1 | tee -a "${EXPERIMENT_LOG}"

        # Prometheus naplók rögzítése háttérben a futtatás időtartama alatt
        start_prom_log_capture "${EXPERIMENT_LOG}"
        sleep_with_progress "${DURATION}" "${_ALG}" "${_CPU}"
        stop_prom_log_capture

        # Futtatás szintű Prometheus napló összefoglaló kiírása
        warns=$(count_lines "${PROM_WARN_FILE}")
        errs=$(count_lines "${PROM_ERR_FILE}")
        echo "    Prometheus: ${warns} warning(s), ${errs} error(s) during run" | \
            tee -a "${EXPERIMENT_LOG}"

        # Prometheus TSDB pillanatkép indítása
        echo "--> Triggering Prometheus snapshot for ALG=${_ALG} CPU=${_CPU}"
        SNAPSHOT_RESPONSE=$(curl -sf -XPOST \
            "${PROMETHEUS_URL}/api/v1/admin/tsdb/snapshot" 2>/dev/null || echo '{"status":"error"}')
        echo "    Snapshot response: ${SNAPSHOT_RESPONSE}"
        echo "    Snapshot: ${SNAPSHOT_RESPONSE}" >> "${EXPERIMENT_LOG}"

        # A pillanatkép nevének kinyerése és rögzítése
        SNAPSHOT_NAME=$(echo "${SNAPSHOT_RESPONSE}" | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('name','unknown'))" \
            2>/dev/null || echo "unknown")

        RESULT_ENTRY="${RESULTS_DIR}/${RUN_ID}.json"
        python3 -c "
import json, sys
entry = {
    'algorithm': '${_ALG}',
    'cpu_limit': '${_CPU}',
    'duration_s': ${DURATION},
    'snapshot': '${SNAPSHOT_NAME}',
    'run_id': '${RUN_ID}',
    'prom_warnings': ${warns},
    'prom_errors': ${errs},
}
print(json.dumps(entry, indent=2))
" > "${RESULT_ENTRY}"

        echo "--> Result metadata saved to ${RESULT_ENTRY}"
        echo ""
    done
done

print_config_bar "$TOTAL_RUNS" "DONE" "-"
echo ""
echo "=== All experiments complete ==="
echo "Experiment finished at $(date)" >> "${EXPERIMENT_LOG}"
echo "Log: ${EXPERIMENT_LOG}"
echo "Results: ${RESULTS_DIR}/"

echo "--> Exporting metrics to ${RESULTS_DIR}/metrics_export.txt"
PROMETHEUS_URL="${PROMETHEUS_URL}" RESULTS_DIR="${RESULTS_DIR}" \
    python3 scripts/export_metrics.py

echo "Done."
