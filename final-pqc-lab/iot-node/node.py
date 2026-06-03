#!/usr/bin/env python3
import json, os, random, time, threading, logging
import psutil
import paho.mqtt.client as mqtt
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

NODE_ID          = os.environ.get("NODE_ID", "node-unknown")
MQTT_BROKER      = os.environ.get("MQTT_BROKER", "pqc-proxy")
MQTT_PORT        = int(os.environ.get("MQTT_PORT", "1883"))
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "5"))
METRICS_PORT     = int(os.environ.get("METRICS_PORT", "9100"))
TOPIC            = f"iot/sensor/{NODE_ID}"

mqtt_messages_total = Counter(
    "mqtt_messages_total", "Total MQTT messages published", ["node_id"])
mqtt_publish_latency_ms = Histogram(
    "mqtt_publish_latency_ms", "MQTT publish latency in ms", ["node_id"],
    buckets=[1,2,5,10,25,50,100,250,500,1000,2500,5000])
cpu_usage_percent = Gauge(
    "node_cpu_usage_percent", "Process CPU usage percent", ["node_id"])
memory_rss_bytes = Gauge(
    "node_memory_rss_bytes", "Resident memory in bytes", ["node_id"])

_pending: dict[int, float] = {}
_lock = threading.Lock()
_seq  = 0

def _sys_metrics():
    proc = psutil.Process()
    cpu_usage_percent.labels(node_id=NODE_ID).set(proc.cpu_percent(interval=None))
    memory_rss_bytes.labels(node_id=NODE_ID).set(proc.memory_info().rss)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info("Connected to MQTT broker at %s:%d", MQTT_BROKER, MQTT_PORT)
    else:
        log.error("MQTT connect failed: %s", reason_code)

def on_publish(client, userdata, mid, reason_code=None, properties=None):
    now = time.monotonic()
    with _lock:
        start = _pending.pop(mid, None)
    if start is not None:
        mqtt_publish_latency_ms.labels(node_id=NODE_ID).observe((now - start) * 1000)

def on_disconnect(client, userdata, flags, reason_code, properties):
    log.warning("Disconnected (reason: %s)", reason_code)

def publish_loop(client):
    global _seq
    while True:
        payload = json.dumps({
            "node_id": NODE_ID, "timestamp": time.time(),
            "sequence": _seq,
            "temperature": round(random.uniform(18.0, 35.0), 2),
            "humidity":    round(random.uniform(30.0, 90.0), 2),
            "pressure":    round(random.uniform(980.0, 1025.0), 2),
        })
        _seq += 1
        t0 = time.monotonic()
        result = client.publish(TOPIC, payload, qos=1)
        with _lock:
            _pending[result.mid] = t0
        mqtt_messages_total.labels(node_id=NODE_ID).inc()
        log.info("Published seq=%d to %s (mid=%d)", _seq - 1, TOPIC, result.mid)
        _sys_metrics()
        time.sleep(PUBLISH_INTERVAL)

def main():
    log.info("IoT node %s starting. Broker: %s:%d, interval: %.1fs",
             NODE_ID, MQTT_BROKER, MQTT_PORT, PUBLISH_INTERVAL)
    start_http_server(METRICS_PORT)
    log.info("Prometheus metrics on :%d", METRICS_PORT)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"iot-{NODE_ID}", clean_session=True)
    client.on_connect    = on_connect
    client.on_publish    = on_publish
    client.on_disconnect = on_disconnect

    backoff = 2
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            break
        except Exception as exc:
            log.error("Cannot connect: %s – retry in %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    client.loop_start()
    try:
        publish_loop(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
