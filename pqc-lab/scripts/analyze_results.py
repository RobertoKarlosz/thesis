#!/usr/bin/env python3
"""analyze_results.py — Offline PQC kísérlet-elemzés a Prometheus HTTP API-n keresztül.

Használat:
    # 1. Indítsd el a Prometheus-t a legutóbbi pillanatképből (lásd lentebb), majd:
    python3 scripts/analyze_results.py

    # Alapértelmezések felülírása:
    PROMETHEUS_URL=http://localhost:9091 RESULTS_DIR=./experiment-results \
        python3 scripts/analyze_results.py

Prometheus pillanatkép indítása (egy sorban):
    SNAP=<pillanatkép-neve>   # pl. 20260603T092318Z-63fc4e390146d965
    docker run --rm -d --name prom-offline -p 9091:9090 \\
      -v "$(pwd)/prometheus-snapshots/${SNAP}:/prometheus" \\
      prom/prometheus \\
      --storage.tsdb.path=/prometheus --web.enable-admin-api
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9091")
RESULTS_DIR    = Path(os.environ.get("RESULTS_DIR", "experiment-results"))
NODE_IDS       = ["node-a", "node-b", "node-c"]


def parse_snapshot_time(snapshot: str) -> datetime:
    """'20260603T092318Z-abc123'  →  UTC-tudatos datetime objektum"""
    ts = snapshot.split("-")[0]
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def instant_query(promql: str, at: float) -> list:
    r = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                     params={"query": promql, "time": at}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["result"]


def latency_quantile(node_id: str, q: float, start: float, end: float) -> float | None:
    """Hisztogram kvantilis a [start, end] intervallumon, az end időpontban kiértékelve."""
    window = int(end - start)
    promql = (
        f"histogram_quantile({q}, sum by (le) ("
        f"rate(mqtt_publish_latency_ms_bucket{{node_id=\"{node_id}\"}}[{window}s])))"
    )
    result = instant_query(promql, end)
    if result:
        v = result[0]["value"][1]
        return float(v) if v != "NaN" else None
    return None


def avg_gauge(metric: str, node_id: str, start: float, end: float) -> float | None:
    window = int(end - start)
    promql = f"avg_over_time({metric}{{node_id=\"{node_id}\"}}[{window}s])"
    result = instant_query(promql, end)
    if result:
        values = [float(s["value"][1]) for s in result if s["value"][1] != "NaN"]
        return sum(values) / len(values) if values else None
    return None


def collect_rows() -> list[dict]:
    rows = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        meta = json.loads(f.read_text())
        snap = meta.get("snapshot", "unknown")
        if snap == "unknown":
            print(f"[skip] {f.name}: no snapshot recorded", file=sys.stderr)
            continue

        end_ts   = parse_snapshot_time(snap).timestamp()
        start_ts = end_ts - meta["duration_s"]

        for node_id in NODE_IDS:
            rows.append({
                "algorithm":      meta["algorithm"],
                "cpu_limit":      float(meta["cpu_limit"]),
                "node_id":        node_id,
                "p50_ms":         latency_quantile(node_id, 0.50, start_ts, end_ts),
                "p95_ms":         latency_quantile(node_id, 0.95, start_ts, end_ts),
                "p99_ms":         latency_quantile(node_id, 0.99, start_ts, end_ts),
                "avg_cpu_pct":    avg_gauge("node_cpu_usage_percent",  node_id, start_ts, end_ts),
                "avg_rss_mb":     _rss_mb(avg_gauge("node_memory_rss_bytes", node_id, start_ts, end_ts)),
            })
    return rows


def _rss_mb(v: float | None) -> float | None:
    return round(v / 1_048_576, 2) if v else None


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No data.")
        return

    headers = ["algorithm", "cpu_limit", "node_id",
               "p50_ms", "p95_ms", "p99_ms", "avg_cpu_pct", "avg_rss_mb"]
    col_w = {h: max(len(h), *(len(fmt(r[h])) for r in rows)) for h in headers}

    def fmt(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    sep = "  ".join("-" * col_w[h] for h in headers)
    hdr = "  ".join(h.ljust(col_w[h]) for h in headers)
    print(hdr)
    print(sep)
    for r in rows:
        print("  ".join(fmt(r[h]).ljust(col_w[h]) for h in headers))


def save_csv(rows: list[dict], path: Path) -> None:
    import csv
    headers = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved: {path}")


def main() -> None:
    print(f"Prometheus : {PROMETHEUS_URL}")
    print(f"Results    : {RESULTS_DIR}\n")

    try:
        requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5).raise_for_status()
    except Exception as e:
        sys.exit(f"Prometheus not reachable at {PROMETHEUS_URL}: {e}")

    rows = collect_rows()
    if not rows:
        sys.exit("No rows collected — check result JSON files and snapshot availability.")

    print_table(rows)
    save_csv(rows, RESULTS_DIR / "summary.csv")


if __name__ == "__main__":
    main()
