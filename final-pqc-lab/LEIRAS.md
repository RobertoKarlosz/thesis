# PQC IoT Lab – Leírás és Használati Útmutató

## 1. A labor célja és architektúrája

Ez a labor egy **Post-Quantum Cryptography (PQC)** alapú IoT kommunikációs környezet, amely azt vizsgálja, hogy a kvantumszámítógép-rezisztens kulcscsere-algoritmusok (pl. ML-KEM-768, BIKE-L1) hogyan befolyásolják az MQTT-alapú IoT-kommunikáció teljesítményét.

### Architektúra áttekintés

```
[IoT Node A] ──plaintext MQTT──► [PQC Proxy A] ──TLS 1.3 + PQC KEM──► [Mosquitto Broker]
[IoT Node B] ──plaintext MQTT──► [PQC Proxy B] ──TLS 1.3 + PQC KEM──► (stunnel TLS wrap)
[IoT Node C] ──plaintext MQTT──► [PQC Proxy C] ──TLS 1.3 + PQC KEM──►

[Prometheus] ◄── metrikák ── [IoT Node-ok + PQC Proxy-k + Node Exporter]
[Grafana]    ◄── lekérdezés ── [Prometheus]
```

**Főbb komponensek:**
- **pqc-base** – Egyedi Docker alap-image Ubuntu 24.04-en, liboqs + oqs-provider + OpenSSL PQC-támogatással
- **mosquitto** – MQTT broker (Mosquitto), stunnel4 TLS-terminálással a 8883-as porton
- **pqc-proxy-{a,b,c}** – Három párhuzamos PQC-proxy, amelyek stunnel4 segítségével TLS 1.3 + PQC KEM csatornán küldik az MQTT-forgalmat a brokerhez; mérnek handshake-késleltetést
- **iot-node-{a,b,c}** – Három szimulált IoT-érzékelő-csomópont (Python), amelyek MQTT-en keresztül küldenek véletlenszerű szenzorAdatokat
- **prometheus** – Metrikagyűjtő (10 s scrape-intervallum)
- **grafana** – Vizualizációs dashboard (előre provisioned)
- **node-exporter** – Gazdagép-szintű metrikák gyűjtője

**A PQC kulcscsere hogyan működik:**  
A TLS-certifikátumok hagyományos ECDSA P-256 alapúak (aláírás), de a TLS 1.3 handshake során a tényleges kulcscsere PQC KEM algoritmust (pl. ML-KEM-768) használ. A `PQC_ALG` környezeti változóval választható meg az algoritmus.

---

## 2. Előfeltételek

| Követelmény | Minimum verzió | Ellenőrzés |
|---|---|---|
| Docker Engine | 24.0+ | `docker --version` |
| Docker Compose | v2.20+ | `docker compose version` |
| Szabad RAM | 4 GB | `free -h` |
| Szabad lemezterület | 10 GB | `df -h .` |
| Operációs rendszer | Linux (x86_64) | – |

> **Megjegyzés:** Az alap-image buildelése 10–20 percet vehet igénybe, mivel le kell fordítani a liboqs és az oqs-provider könyvtárakat.

---

## 3. Az alap Docker image buildelése

A többi image az egyedi `pqc-base` image-re épül, amelyet **először** kell megbuildelni:

```bash
cd /path/to/final-pqc-lab

docker build -t pqc-base:latest ./base-image/
```

A build sikeres végrehajtása után ellenőrizd, hogy az oqsprovider betöltődik:

```bash
docker run --rm pqc-base:latest openssl list -providers
```

Várt kimenet: a listában szerepeljen az `oqsprovider`.

---

## 4. TLS tanúsítványok generálása

A labor TLS-t használ a proxy és a broker között. Generáld a tanúsítványokat:

```bash
bash scripts/generate_certs.sh
```

Alapértelmezés szerint ECDSA P-256 tanúsítványokat hoz létre a `./certs/` könyvtárba:
- `ca.key` / `ca.crt` – CA kulcs és önaláírt tanúsítvány
- `server.key` / `server.crt` – Mosquitto szervertanúsítvány (SAN: `mosquitto`, `localhost`, `127.0.0.1`)

Más algoritmushoz (csak a KEM algoritmushoz tartozó tanúsítványok újragenerálása szükséges, a cert maga marad P-256):

```bash
PQC_ALG=bikel1 bash scripts/generate_certs.sh
```

---

## 5. Az összes szolgáltatás elindítása

```bash
cd /path/to/final-pqc-lab

docker compose up -d --build
```

Az indítás sorrendje automatikusan kontrollált a `depends_on` direktívákkal:
1. `mosquitto` indul el elsőként
2. `pqc-proxy-{a,b,c}` megvárja a mosquitto-t
3. `iot-node-{a,b,c}` megvárja a megfelelő proxyt
4. `prometheus` és `grafana` az observability hálózaton futnak

A szolgáltatások állapotának ellenőrzése:

```bash
docker compose ps
```

---

## 6. Ellenőrzési lépések

### Logok megtekintése

```bash
# Mosquitto logs
docker compose logs mosquitto

# PQC proxy-a logs (handshake mérések)
docker compose logs pqc-proxy-a

# IoT node-a logs
docker compose logs iot-node-a

# Összes log, valós időben
docker compose logs -f
```

### PQC handshake kézi tesztelése

A tanúsítványok generálása után ellenőrizd a PQC TLS kapcsolatot (az alap-image-ből):

```bash
docker run --rm --network pqc-iot-lab_broker-net \
    -v "$(pwd)/certs:/certs:ro" \
    pqc-base:latest \
    openssl s_client \
        -connect mosquitto:8883 \
        -CAfile /certs/ca.crt \
        -groups mlkem768 \
        -tls1_3 </dev/null
```

A kimenetben ellenőrizd: `Server Temp Key: X25519MLKEM768` (vagy a beállított algoritmus).

### Prometheus metrikák

Nyisd meg böngészőben: [http://localhost:9090](http://localhost:9090)

Hasznos PromQL lekérdezések:
```
handshake_latency_ms
mqtt_messages_total
node_memory_rss_bytes
```

### Grafana dashboard

Nyisd meg: [http://localhost:3000](http://localhost:3000)  
Bejelentkezés: `admin` / `admin`

A „PQC IoT Lab Overview" dashboard automatikusan betöltődik.

### Metrikák közvetlen lekérdezése curl-lel

```bash
# PQC proxy metrikák
curl http://localhost:9101/metrics

# IoT node-a metrikák
curl http://localhost:9110/metrics

# Node exporter (gazdagép metrikák)
curl http://localhost:9100/metrics
```

---

## 7. Az algoritmus váltása (PQC_ALG módosítása)

Az aktív PQC KEM algoritmus a `PQC_ALG` változóval vezérelhető. Az algoritmus váltásához:

**1. lépés:** Szerkeszd a `.env` fájlt:

```bash
# Lehetséges értékek: mlkem768, bikel1, bikel3, bikel5, x25519
PQC_ALG=bikel1
```

**2. lépés:** Generáld újra a tanúsítványokat az új algoritmushoz:

```bash
PQC_ALG=bikel1 bash scripts/generate_certs.sh
```

**3. lépés:** Indítsd újra az érintett szolgáltatásokat:

```bash
docker compose up -d --force-recreate mosquitto pqc-proxy-a pqc-proxy-b pqc-proxy-c
```

Az IoT node-oknak nem kell újraindulniuk, mivel ők plaintext MQTT-en kommunikálnak a proxy-val.

> **Megjegyzés:** Az `x25519` klasszikus Diffie-Hellman kulcscsere (nem PQC), referencia-benchmarkként érdemes használni.

---

## 8. A kísérletmátrix futtatása

A `run_experiment.sh` szkript automatikusan végigiterál az összes algoritmus × CPU-limit kombináción, és minden futáshoz Prometheus TSDB snapshotot készít.

```bash
# Alapértelmezett futtatás (180 s/konfiguráció)
bash scripts/run_experiment.sh

# Rövidített futtatás teszteléshez (30 s/konfiguráció)
DURATION=30 bash scripts/run_experiment.sh

# Egyedi eredmények könyvtára
RESULTS_DIR=./my-results bash scripts/run_experiment.sh
```

**Kísérletmátrix:**

| Algoritmus | CPU limitek |
|---|---|
| mlkem768 | 0.1, 0.25, 0.5, 1.0 |
| bikel1 | 0.1, 0.25, 0.5, 1.0 |
| x25519 | 0.1, 0.25, 0.5, 1.0 |

Összesen: 12 konfiguráció × `DURATION` másodperc = ~36 perc (alapértelmezetten).

Az eredmények a `./experiment-results/` könyvtárba kerülnek:
- `experiment_YYYYMMDD_HHMMSS.log` – teljes napló
- `{alg}_cpu{limit}_{timestamp}.json` – futásonkénti összefoglaló

---

## 9. A Grafana dashboard paneljeinek magyarázata

| Panel | Típus | Leírás |
|---|---|---|
| **PQC TLS Handshake Latency** | Idősor | A PQC KEM handshake átlagos ideje milliszekundumban, proxy-nként és algoritmusonként |
| **Handshake Latency per Proxy** | Mérőóra | Utolsó mért handshake-késleltetés proxy-nként (zöld < 100 ms, sárga < 500 ms, piros ≥ 500 ms) |
| **CPU Usage per Node** | Idősor | Folyamat-szintű CPU-felhasználás arány (1 perces rate), példányonként |
| **Resident Memory per Node** | Idősor | Folyamat RSS memóriája bájtban, csomópontonként |
| **MQTT Publish Latency p50/p95** | Idősor | MQTT üzenetküldési késleltetés 50. és 95. percentilis értékei (1 perces ablak) |
| **MQTT Messages Published** | Stat | Az összes elküldött MQTT üzenet száma csomópontonként |
| **Network Throughput** | Idősor | Hálózati áteresztőképesség (TX/RX bájtok/s), gazdagép-szintű interfészenként |
| **IoT Nodes Online** | Stat | Aktív (UP állapotú) IoT csomópontok száma |
| **PQC Proxies Online** | Stat | Aktív PQC proxy konténerek száma |


### Teljes leállítás és tisztítás

```bash
# Leállítás (adatok megőrzése)
docker compose down

# Leállítás + összes volume törlése
docker compose down -v

# Összes pqc-* image törlése
docker images | grep pqc | awk '{print $3}' | xargs docker rmi -f
```
