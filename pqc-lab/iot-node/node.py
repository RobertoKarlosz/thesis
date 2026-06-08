#!/usr/bin/env python3
"""IoT érzékelő csomópont – MQTT üzeneteket küld PQC proxyn keresztül, Prometheus metrikákat tesz elérhetővé."""

import json
import os
import random
import time
import threading
import logging

import psutil
import paho.mqtt.client as mqtt
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Konfiguráció környezeti változókból ───────────────────────────────────────
NODE_ID = os.environ.get("NODE_ID", "node-unknown")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "pqc-proxy")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "5"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9100"))
TOPIC = f"iot/sensor/{NODE_ID}"

# ── Prometheus metrikák ───────────────────────────────────────────────────────
mqtt_messages_total = Counter(
    "mqtt_messages_total",
    "Összes elküldött MQTT üzenet (publish() hívások száma, nem visszaigazolt kézbesítések)",
    ["node_id"],
)
mqtt_publish_latency_ms = Histogram(
    "mqtt_publish_latency_ms",
    "MQTT küldési késleltetés milliszekundumban (publish() → on_publish visszahívás). "
    "Az időtúllépéses bejegyzések (PUBACK nem érkezett PENDING_TIMEOUT_S-en belül) "
    "a tényleges eltelt idővel kerülnek rögzítésre, láthatóvá téve a lassú/hibás kapcsolatokat.",
    ["node_id"],
    buckets=[1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 15000, 30000],
)
mqtt_publish_acked_total = Counter(
    "mqtt_publish_acked_total",
    "Összes fogadott MQTT PUBACK visszaigazolás (QoS 1 kézbesítés megerősítve)",
    ["node_id"],
)
mqtt_publish_timeout_total = Counter(
    "mqtt_publish_timeout_total",
    "MQTT küldések, amelyekre nem érkezett PUBACK a PENDING_TIMEOUT_S határidőn belül",
    ["node_id"],
)
mqtt_reconnect_total = Counter(
    "mqtt_reconnect_total",
    "Összes MQTT bróker-leválasztási esemény (minden esemény újracsatlakozási kísérletet indít)",
    ["node_id"],
)
cpu_usage_percent = Gauge(
    "node_cpu_usage_percent",
    "Folyamat CPU-használat százalékban",
    ["node_id"],
)
memory_rss_bytes = Gauge(
    "node_memory_rss_bytes",
    "Rezidens memóriahasználat bájtban",
    ["node_id"],
)

# ── Állapot ──────────────────────────────────────────────────────────────────
_pending_publishes: dict[int, float] = {}
_lock = threading.Lock()
_sequence = 0

PENDING_TIMEOUT_S = float(os.environ.get("PENDING_TIMEOUT_S", "30"))


def _update_system_metrics() -> None:
    proc = psutil.Process()
    cpu_usage_percent.labels(node_id=NODE_ID).set(proc.cpu_percent(interval=None))
    mem = proc.memory_info()
    memory_rss_bytes.labels(node_id=NODE_ID).set(mem.rss)


# ── MQTT visszahívások ────────────────────────────────────────────────────────
def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
    if reason_code == 0:
        log.info("Connected to MQTT broker at %s:%d", MQTT_BROKER, MQTT_PORT)
    else:
        log.error("MQTT connect failed, reason code: %s", reason_code)


def on_publish(client: mqtt.Client, userdata, mid, reason_code=None, properties=None) -> None:
    now = time.monotonic()
    with _lock:
        start = _pending_publishes.pop(mid, None)
    if start is not None:
        latency = (now - start) * 1000.0
        mqtt_publish_latency_ms.labels(node_id=NODE_ID).observe(latency)
        mqtt_publish_acked_total.labels(node_id=NODE_ID).inc()
        log.debug("MID %d latency: %.2f ms", mid, latency)


def on_disconnect(client, userdata, flags, reason_code, properties) -> None:
    log.warning("Disconnected from MQTT broker (reason: %s), will reconnect.", reason_code)
    mqtt_reconnect_total.labels(node_id=NODE_ID).inc()


def _reaper_loop() -> None:
    """Rendszeresen lejáratja azokat a függőben lévő küldéseket, amelyekre nem érkezett PUBACK.

    Enélkül egy meghibásodott PQC TLS alagút (pl. BIKE) esetén az összes késleltetési
    megfigyelés eltűnne a hisztogramból, láthatatlanná téve a problémát.
    A PENDING_TIMEOUT_S elteltével a tényleges eltelt idő kerül rögzítésre, így a hisztogram
    a tényleges kézbesítési hiba költségét mutatja, nem pedig üres adatot ad vissza.
    """
    while True:
        time.sleep(5)
        now = time.monotonic()
        stale: dict[int, float] = {}
        with _lock:
            for mid, start in list(_pending_publishes.items()):
                if now - start >= PENDING_TIMEOUT_S:
                    stale[mid] = _pending_publishes.pop(mid)
        for mid, start in stale.items():
            elapsed_ms = (now - start) * 1000.0
            mqtt_publish_latency_ms.labels(node_id=NODE_ID).observe(elapsed_ms)
            mqtt_publish_timeout_total.labels(node_id=NODE_ID).inc()
            log.warning("MID %d timed out (no PUBACK) after %.0f ms", mid, elapsed_ms)


# ── Küldő ciklus ─────────────────────────────────────────────────────────────
def publish_loop(client: mqtt.Client) -> None:
    global _sequence
    proc = psutil.Process()

    while True:
        payload = {
            "node_id": NODE_ID,
            "timestamp": time.time(),
            "sequence": _sequence,
            "temperature": round(random.uniform(18.0, 35.0), 2),
            "humidity": round(random.uniform(30.0, 90.0), 2),
            "pressure": round(random.uniform(980.0, 1025.0), 2),
        }
        _sequence += 1
        raw = json.dumps(payload)

        t0 = time.monotonic()
        result = client.publish(TOPIC, raw, qos=1)
        with _lock:
            _pending_publishes[result.mid] = t0

        mqtt_messages_total.labels(node_id=NODE_ID).inc()
        log.info("Published seq=%d to %s (mid=%d)", payload["sequence"], TOPIC, result.mid)

        _update_system_metrics()
        time.sleep(PUBLISH_INTERVAL)


# ── Főprogram ────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("IoT node %s starting. Broker: %s:%d, interval: %.1fs",
             NODE_ID, MQTT_BROKER, MQTT_PORT, PUBLISH_INTERVAL)

    start_http_server(METRICS_PORT)
    log.info("Prometheus metrics on :%d", METRICS_PORT)

    threading.Thread(target=_reaper_loop, daemon=True, name="puback-reaper").start()
    log.info("PUBACK reaper started (timeout=%.0fs)", PENDING_TIMEOUT_S)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"iot-{NODE_ID}",
        clean_session=True,
    )
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.on_disconnect = on_disconnect

    # Újracsatlakozás növekvő várakozási idővel
    backoff = 2
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as exc:
            log.error("Cannot connect to broker: %s – retrying in %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    client.loop_start()

    try:
        publish_loop(client)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
