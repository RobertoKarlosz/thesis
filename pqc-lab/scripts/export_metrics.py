#!/usr/bin/env python3
"""export_metrics.py — Prometheus lekérdezési eredmények exportálása formázott szöveges fájlba.

Használat:
    python3 scripts/export_metrics.py
    PROMETHEUS_URL=http://localhost:9091 python3 scripts/export_metrics.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9091")
RESULTS_DIR    = Path(os.environ.get("RESULTS_DIR", "experiment-results"))
NODE_IDS       = ["temperature-sensor-1", "temperature-sensor-2", "temperature-sensor-3"]

DEVICE_NAMES = {
    "0.026":  "ESP32 (Xtensa LX7 240 MHz)",
    "0.12":  "RPi Zero 2W (Cortex-A53 1 GHz)",
    "0.25":  "RPi 3B+ (Cortex-A53 1.4 GHz)",
    "0.5":   "RPi 4B (Cortex-A72 1.5 GHz)",
    "1.0":   "Industrial gateway (Intel Atom)"
}
OUT_FILE       = RESULTS_DIR / "metrics_export.txt"


def parse_snapshot_time(snapshot: str) -> datetime:
    ts = snapshot.split("-")[0]
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def query(promql: str, at: float) -> list:
    r = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                     params={"query": promql, "time": at}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["result"]


def _val(results: list) -> float | None:
    if results:
        v = results[0]["value"][1]
        return float(v) if v not in ("NaN", "+Inf", "-Inf") else None
    return None


def _mb(v: float | None) -> float | None:
    return v / 1_048_576 if v is not None else None


def _kb(v: float | None) -> float | None:
    return v / 1_024 if v is not None else None


def _pct(v: float | None) -> float | None:
    return v * 100 if v is not None else None


def fetch_node(node_id: str, start: float, end: float) -> dict:
    w = int(end - start)
    def q(promql): return _val(query(promql, end))

    published = q(f'rate(mqtt_messages_total{{node_id="{node_id}"}}[{w}s])')
    acked     = q(f'rate(mqtt_publish_acked_total{{node_id="{node_id}"}}[{w}s])')
    timeouts  = q(f'rate(mqtt_publish_timeout_total{{node_id="{node_id}"}}[{w}s])')
    reconnects = q(f'increase(mqtt_reconnect_total{{node_id="{node_id}"}}[{w}s])')

    # Kézbesítési arány: visszaigazolt / elküldött (None, ha nem volt küldés)
    delivery_ratio: float | None = None
    if published is not None and published > 0 and acked is not None:
        delivery_ratio = acked / published

    return {
        "p50":           q(f'histogram_quantile(0.50,sum by(le)(rate(mqtt_publish_latency_ms_bucket{{node_id="{node_id}"}}[{w}s])))'),
        "p95":           q(f'histogram_quantile(0.95,sum by(le)(rate(mqtt_publish_latency_ms_bucket{{node_id="{node_id}"}}[{w}s])))'),
        "p99":           q(f'histogram_quantile(0.99,sum by(le)(rate(mqtt_publish_latency_ms_bucket{{node_id="{node_id}"}}[{w}s])))'),
        "cpu":           q(f'avg_over_time(node_cpu_usage_percent{{node_id="{node_id}"}}[{w}s])'),
        "mem_mb":        _mb(q(f'avg_over_time(node_memory_rss_bytes{{node_id="{node_id}"}}[{w}s])')),
        "rate":          published,
        "delivery_ratio": delivery_ratio,
        "timeouts_rate": timeouts,
        "reconnects":    reconnects,
    }


PROXY_SERVICES = ["pqc-proxy-a", "pqc-proxy-b", "pqc-proxy-c"]


def fetch_proxy(service: str, start: float, end: float) -> dict:
    """Proxy szintű metrikák lekérdezése: CPU-használat (cAdvisor) és kézfogás késleltetése."""
    w = int(end - start)
    def q(promql): return _val(query(promql, end))
    return {
        # CPU: az összes cAdvisor sorozat összege ehhez a szolgáltatáshoz, a root cgroup kizárásával.
        # A Docker Compose által beállított container_label_com_docker_compose_service értéket használja.
        "cpu_pct": _pct(q(
            f'sum(rate(container_cpu_usage_seconds_total{{'
            f'container_label_com_docker_compose_service="{service}",'
            f'id!="/"'
            f'}}[{w}s]))')),
        # Kézfogás késleltetése a proxy indításakor kerül írásra; a proxy címke = PROXY_ID env változó
        # (szolgáltatásnév), nem a véletlenszerű konténer hostnév.
        "handshake_ms": q(
            f'handshake_latency_ms{{proxy="{service}"}}'),
    }


def fetch_host(start: float, end: float) -> dict:
    """A gazdagép node_exporter metrikáinak lekérdezése a [start, end] intervallumon."""
    w = int(end - start)
    def q(promql): return _val(query(promql, end))
    return {
        # Teljes CPU-kihasználtság az összes magon (1 - tétlen arány)
        "cpu_pct": _pct(q(
            f'1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[{w}s]))')),
        # Módok szerinti bontás
        "cpu_user_pct":   _pct(q(f'avg(rate(node_cpu_seconds_total{{mode="user"}}[{w}s]))')),
        "cpu_system_pct": _pct(q(f'avg(rate(node_cpu_seconds_total{{mode="system"}}[{w}s]))')),
        # Memória
        "mem_used_mb": _mb(q(
            f'avg_over_time(node_memory_MemTotal_bytes[{w}s])'
            f' - avg_over_time(node_memory_MemAvailable_bytes[{w}s])')),
        "mem_total_mb": _mb(q(f'node_memory_MemTotal_bytes')),
        # Hálózat (loopback nélkül), interfészeken összesítve
        "net_tx_kbs": _kb(q(
            f'sum(rate(node_network_transmit_bytes_total{{device!="lo"}}[{w}s]))')),
        "net_rx_kbs": _kb(q(
            f'sum(rate(node_network_receive_bytes_total{{device!="lo"}}[{w}s]))')),
        # Lemez I/O
        "disk_read_kbs":  _kb(q(f'sum(rate(node_disk_read_bytes_total[{w}s]))')),
        "disk_write_kbs": _kb(q(f'sum(rate(node_disk_written_bytes_total[{w}s]))')),
        # Rendszerterheltség
        "load1":  q(f'avg_over_time(node_load1[{w}s])'),
        "load5":  q(f'avg_over_time(node_load5[{w}s])'),
    }


def fmt(v, decimals=2):
    return f"{v:.{decimals}f}" if v is not None else "—"


def main():
    try:
        requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5).raise_for_status()
    except Exception as e:
        sys.exit(f"Prometheus not reachable at {PROMETHEUS_URL}: {e}")

    json_files = sorted(RESULTS_DIR.glob("*.json"))
    if not json_files:
        sys.exit("No result JSON files found.")

    lines = []
    summary: dict[str, list[float]] = {}

    lines.append("=" * 76)
    lines.append("  PQC Experiment — Metrics Export")
    lines.append(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Prometheus: {PROMETHEUS_URL}")
    lines.append(f"  Source    : {RESULTS_DIR}")
    lines.append("=" * 76)

    node_col  = "{:<8}  {:>8}  {:>8}  {:>8}  {:>8}  {:>8}  {:>10}  {:>9}  {:>9}  {:>8}"
    sep = "-" * 100

    for i, f in enumerate(json_files, 1):
        meta = json.loads(f.read_text())
        snap = meta.get("snapshot", "unknown")
        if snap == "unknown":
            continue

        end_dt   = parse_snapshot_time(snap)
        end_ts   = end_dt.timestamp()
        start_ts = end_ts - meta["duration_s"]
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)

        alg = meta["algorithm"]
        cpu_limit = meta["cpu_limit"]

        device = DEVICE_NAMES.get(cpu_limit, f"custom ({cpu_limit} core)")

        lines.append("")
        lines.append(f"RUN {i:02d}: {alg}  @  CPU={cpu_limit}  [{device}]")
        lines.append(f"  Window : {start_dt.strftime('%Y-%m-%d %H:%M:%S')} – "
                     f"{end_dt.strftime('%H:%M:%S')} UTC  ({meta['duration_s']}s)")
        if meta.get("prom_warnings") or meta.get("prom_errors"):
            lines.append(f"  Prometheus during run: "
                         f"{meta.get('prom_warnings', 0)} warning(s), "
                         f"{meta.get('prom_errors', 0)} error(s)")

        # ── IoT csomópont metrikák ───────────────────────────────────────────
        lines.append("")
        lines.append("  IoT nodes (process-level metrics)")
        lines.append("  " + node_col.format(
            "node", "p50(ms)", "p95(ms)", "p99(ms)", "cpu(%)", "mem(MB)",
            "rate(msg/s)", "ack_ratio", "tmout/s", "reconn"))
        lines.append("  " + sep)

        for node_id in NODE_IDS:
            d = fetch_node(node_id, start_ts, end_ts)
            dr = d["delivery_ratio"]
            dr_str = f"{dr:.3f}" if dr is not None else "—"
            lines.append("  " + node_col.format(
                node_id,
                fmt(d["p50"]), fmt(d["p95"]), fmt(d["p99"]),
                fmt(d["cpu"]), fmt(d["mem_mb"]), fmt(d["rate"], 3),
                dr_str, fmt(d["timeouts_rate"], 4), fmt(d["reconnects"], 1),
            ))
            if d["p99"] is not None:
                summary.setdefault(alg, []).append(d["p99"])

        # ── Proxy metrikák (cAdvisor + handshake_latency_ms) ────────────────
        proxy_col = "{:<14}  {:>10}  {:>14}"
        lines.append("  PQC Proxies")
        lines.append("  " + proxy_col.format("proxy", "cpu_avg(%)", "handshake(ms)"))
        lines.append("  " + sep)
        for svc in PROXY_SERVICES:
            p = fetch_proxy(svc, start_ts, end_ts)
            lines.append("  " + proxy_col.format(
                svc,
                fmt(p["cpu_pct"]),
                fmt(p["handshake_ms"]),
            ))
        lines.append("")

        # ── Gazdagép metrikák (node_exporter) ───────────────────────────────
        h = fetch_host(start_ts, end_ts)
        lines.append("")
        lines.append("  Host (node_exporter)")
        lines.append(f"  {'':4}  {'cpu_total(%)':>12}  {'cpu_user(%)':>11}  "
                     f"{'cpu_sys(%)':>10}  {'load1':>6}  {'load5':>6}")
        lines.append("  " + sep)
        lines.append(f"  {'':4}  {fmt(h['cpu_pct']):>12}  {fmt(h['cpu_user_pct']):>11}  "
                     f"{fmt(h['cpu_system_pct']):>10}  {fmt(h['load1']):>6}  {fmt(h['load5']):>6}")
        lines.append("")
        lines.append(f"  {'':4}  {'mem_used(MB)':>12}  {'mem_total(MB)':>13}  "
                     f"{'net_tx(KB/s)':>12}  {'net_rx(KB/s)':>12}  "
                     f"{'disk_r(KB/s)':>12}  {'disk_w(KB/s)':>12}")
        lines.append("  " + sep)
        lines.append(f"  {'':4}  {fmt(h['mem_used_mb']):>12}  {fmt(h['mem_total_mb']):>13}  "
                     f"{fmt(h['net_tx_kbs']):>12}  {fmt(h['net_rx_kbs']):>12}  "
                     f"{fmt(h['disk_read_kbs']):>12}  {fmt(h['disk_write_kbs']):>12}")
        lines.append("")

    # ── Összefoglaló ──────────────────────────────────────────────────────────
    lines.append("=" * 76)
    lines.append("  ÖSSZEFOGLALÓ — átlagos p99 késleltetés algoritmusonként (összes csomópont és CPU-korlát alapján)")
    lines.append("")
    for alg, vals in sorted(summary.items()):
        avg = sum(vals) / len(vals)
        lines.append(f"  {alg:<12}  {avg:>8.2f} ms  (n={len(vals)})")
    lines.append("=" * 76)

    output = "\n".join(lines)
    print(output)
    OUT_FILE.write_text(output + "\n")
    print(f"\nSaved: {OUT_FILE}")


if __name__ == "__main__":
    main()
