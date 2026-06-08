# PQC IoT Lab

Docker-alapú kísérleti labor posztkvantum-kriptográfiai (PQC) algoritmusok IoT MQTT kommunikációra gyakorolt hatásának vizsgálatához.

A labor három szimulált IoT szenzorcsomópontot tartalmaz, amelyek stunnel sidecar proxyn és PQC-TLS 1.3 kapcsolaton keresztül publikálnak MQTT QoS 1 üzeneteket egy Eclipse Mosquitto brokernek. A mérési adatokat Prometheus gyűjti, Grafana vizualizálja.

---

## Előfeltételek

| Szoftver | Minimális verzió | Megjegyzés |
|---|---|---|
| Docker Engine | 24.0 | |
| Docker Compose | 2.20 (plugin) | `docker compose version` |
| OpenSSL | 3.x | tanúsítványgeneráláshoz |
| Python 3 | 3.10 | elemzőszriptek futtatásához |
| Python `requests` csomag | — | `pip install requests` |

---

## Könyvtárszerkezet

```
pqc-lab/
├── .env                        # alapértelmezett futtatási paraméterek
├── docker-compose.yml          # a teljes labor service-leírása
├── base-image/                 # liboqs + oqs-provider alap Docker image
├── pqc-proxy/                  # stunnel kliens proxy (PQC-TLS kliens oldal)
├── mosquitto-oqs/              # Eclipse Mosquitto + stunnel szerver (TLS termináció)
├── iot-node/                   # Python MQTT szenzorcsomópont
├── prometheus/                 # Prometheus gyűjtési konfiguráció
├── grafana/                    # Grafana adatforrás + dashboard provisioning
├── certs/                      # generált TLS tanúsítványok (git-ignored)
├── experiment-results/         # mérési eredmények, pillanatképek (git-ignored)
└── scripts/
    ├── generate_certs.sh       # ECDSA P-256 tanúsítványlánc generálása
    ├── run_experiment.sh       # automatikus kísérletfuttató
    ├── export_metrics.py       # metrikák exportálása Prometheus API-n keresztül
    └── analyze_results.py      # offline elemzés és diagramgenerálás
```

---

## Gyors indítás

### 1. Docker image-ek felépítése

```bash
docker compose build
```

Az első build hosszabb ideig tarthat (~10–20 perc), mert a `base-image` lefordítja a `liboqs` és `oqs-provider` könyvtárakat.

### 2. TLS tanúsítványok generálása

```bash
bash scripts/generate_certs.sh
```

Ez létrehozza a `certs/` mappában az ECDSA P-256 CA- és szertanúsítványokat. A tanúsítványokat minden kísérlet előtt automatikusan újragenerálja a `run_experiment.sh` szkript.

### 3. Egyetlen kísérlet futtatása (kézi mód)

Állítsd be a paramétereket a `.env` fájlban:

```
PQC_ALG=mlkem768       # vizsgált algoritmus
NODE_CPUS=0.5          # IoT csomópontok CPU-korlátja (Docker mag)
PROXY_CPUS=0.5         # proxy CPU-korlátja
PUBLISH_INTERVAL=5     # MQTT publish intervallum (másodperc)
```

Majd indítsd el a labort:

```bash
docker compose up -d
```

A Grafana dashboard elérhető: [http://localhost:3000](http://localhost:3000) (admin/admin)  
A Prometheus elérhető: [http://localhost:9090](http://localhost:9090)

A labor leállításához:

```bash
docker compose down
```

### 4. Automatikus kísérletsorozat futtatása

A `run_experiment.sh` szkript végigfuttatja az összes algoritmus × CPU-szint kombinációt:

```bash
# Összes algoritmus × összes CPU-szint (8 × 5 = 40 futtatás, alapértelmezett 900 s/futtatás)
bash scripts/run_experiment.sh

# Csak egy algoritmus, összes CPU-szint
bash scripts/run_experiment.sh --alg mlkem768

# Csak egy CPU-szint, összes algoritmus
bash scripts/run_experiment.sh --cpu 0.5

# Egyetlen futtatás, egyedi időtartammal
bash scripts/run_experiment.sh --alg mlkem768 --cpu 0.5 --duration 120
```

**Vizsgált algoritmusok:** `mlkem512`, `mlkem768`, `mlkem1024`, `X25519MLKEM768`, `bikel1`, `bikel3`, `bikel5`, `x25519`

**CPU-szintek és az általuk modellezett eszközök:**

| CPU-korlát | Modellezett eszköz |
|---|---|
| 0.026 mag | ESP32 (Xtensa LX7 240 MHz) |
| 0.12 mag | Raspberry Pi Zero 2W |
| 0.25 mag | Raspberry Pi 3B+ |
| 0.50 mag | Raspberry Pi 4B |
| 1.00 mag | Ipari átjáró / Intel Atom szintű eszköz |

A kísérlet futása közben minden futtatás végén Prometheus TSDB pillanatkép készül, a metaadatok `experiment-results/<run_id>.json` fájlba kerülnek.

### 5. Metrikák exportálása

```bash
python3 scripts/export_metrics.py
```

Lekérdezi a Prometheus HTTP API-t és formázott szöveges fájlba írja a mért metrikákat (`experiment-results/metrics_export.txt`). A Prometheusnak futnia kell a parancs végrehajtásakor.

> A `run_experiment.sh` szkript a kísérletsorozat végén automatikusan meghívja ezt a szkriptet.

### 6. Eredmények elemzése

```bash
python3 scripts/analyze_results.py
```

Offline elemzést és diagramokat készít az exportált metrikákból. Ehhez a Prometheusnak egy pillanatképből visszaállítva kell futnia:

```bash
# Pillanatkép visszaállítása (a <pillanatkép-neve> az experiment-results/*.json fájlban szerepel)
SNAP=<pillanatkép-neve>
docker run --rm -d --name prom-offline -p 9091:9090 \
  -v "$(pwd)/prometheus-snapshots/${SNAP}:/prometheus" \
  prom/prometheus \
  --storage.tsdb.path=/prometheus --web.enable-admin-api

# Elemzés futtatása
PROMETHEUS_URL=http://localhost:9091 python3 scripts/analyze_results.py
```

---

## Konfiguráció

### Környezeti változók

| Változó | Alapértelmezés | Leírás |
|---|---|---|
| `PQC_ALG` | `mlkem768` | Vizsgált PQC kulcscsere-algoritmus |
| `NODE_CPUS` | `0.5` | IoT csomópontok Docker CPU-korlátja |
| `PROXY_CPUS` | `0.5` | PQC proxy Docker CPU-korlátja |
| `PUBLISH_INTERVAL` | `5` | MQTT publish ciklus intervalluma (s) |
| `DURATION` | `900` | Kísérlet időtartama futtatásonként (s) |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus elérési URL |
| `RESULTS_DIR` | `./experiment-results` | Eredménymappa |

---

## Architektúra

```
[IoT csomópont] ──plaintext MQTT──> [stunnel proxy (PQC-TLS kliens)]
                                              │
                                     PQC-TLS 1.3 (KEM: PQC_ALG)
                                              │
                               [stunnel szerver (TLS termináció)]
                                              │
                                    plaintext MQTT (belső)
                                              │
                                     [Mosquitto broker]
                                              │
                               [Prometheus] ──> [Grafana]
```

A PQC algoritmus kizárólag a TLS kézfogás kulcscsere (KEM) fázisában jelenik meg. Az adattitkosítás minden esetben AES-128-GCM, a szessziókulcsot a KEM állítja elő.
