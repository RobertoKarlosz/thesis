# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    libssl-dev \
    python3-dev \
    git \
    curl \
    astyle \
    pkg-config \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# liboqs fordítása
WORKDIR /build
RUN git clone --depth 1 --branch main https://github.com/open-quantum-safe/liboqs.git
WORKDIR /build/liboqs/build
RUN cmake .. \
    -GNinja \
    -DOQS_DIST_BUILD=ON \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DOQS_USE_OPENSSL=ON \
    -DOQS_ENABLE_KEM_BIKE=ON \
    && ninja -j$(nproc) \
    && ninja install \
    && ldconfig

# oqs-provider fordítása; a .so fájlt explicit módon /usr/local/lib/ossl-modules/ alá
# irányítjuk, hogy független legyen a rendszer OpenSSL-modul útvonalától (ami architektúrafüggő).
WORKDIR /build
RUN git clone --depth 1 https://github.com/open-quantum-safe/oqs-provider.git
WORKDIR /build/oqs-provider
RUN cmake -S . -B build \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -Dliboqs_DIR=/usr/local/lib/cmake/liboqs \
    -DOPENSSL_MODULES_PATH=/usr/local/lib/ossl-modules \
    && cmake --build build -j$(nproc) \
    && cmake --install build

# Biztonsági megoldás: keresés azon a helyen is, ahová a cmake esetleg elhelyezte
RUN mkdir -p /usr/local/lib/ossl-modules && \
    find / -maxdepth 12 -name 'oqsprovider.so' 2>/dev/null \
        ! -path '/usr/local/lib/ossl-modules/oqsprovider.so' \
        -exec cp -v {} /usr/local/lib/ossl-modules/ \; && \
    echo "=== ossl-modules in builder ===" && \
    ls -la /usr/local/lib/ossl-modules/

# ── Végleges image ───────────────────────────────────────────────────────────
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    openssl \
    ca-certificates \
    python3 \
    python3-pip \
    curl \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# A teljes /usr/local könyvtár másolása a builder-ből, hogy megőrizzük a symlinkeket és cmake fájlokat
COPY --from=builder /usr/local/ /usr/local/

# /usr/local/lib regisztrálása a dinamikus linkerben
RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/usr-local.conf && ldconfig

# Önállóan használható OpenSSL konfiguráció írása, amely aktiválja az oqsprovider-t.
# Az Ubuntu 24.04 rendszer openssl.cnf fájljában az openssl_conf ki van kommentelve,
# ezért a konfigurációt teljes egészében az OPENSSL_CONF változón keresztül kezeljük.
RUN cat > /etc/ssl/oqs-openssl.cnf <<'EOF'
openssl_conf = openssl_init

[openssl_init]
providers = provider_sect
ssl_conf = ssl_sect

[ssl_sect]
system_default = tls_system_default

# A kísérletekben használt összes PQC csoport felsorolása, hogy a TLS kézfogás
# mindkét oldala (kliens és szerver) hirdesse és elfogadja azokat.
[tls_system_default]
Groups = mlkem512:mlkem768:mlkem1024:X25519MLKEM768:bikel1:bikel3:bikel5:x25519:P-256:P-384:P-521

[provider_sect]
default = default_sect
oqsprovider = oqsprovider_sect

[default_sect]
activate = 1

[oqsprovider_sect]
module = /usr/local/lib/ossl-modules/oqsprovider.so
activate = 1
EOF

ENV OPENSSL_CONF=/etc/ssl/oqs-openssl.cnf
ENV OPENSSL_MODULES=/usr/local/lib/ossl-modules

# Diagnosztika és ellenőrzés
RUN echo "=== ossl-modules ===" && \
    ls -la /usr/local/lib/ossl-modules/ && \
    echo "=== ldd oqsprovider.so ===" && \
    ldd /usr/local/lib/ossl-modules/oqsprovider.so && \
    echo "=== openssl list -providers ===" && \
    openssl list -providers && \
    openssl list -providers | grep -q oqsprovider && \
    echo "oqsprovider loaded OK"

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD openssl list -providers | grep -q oqsprovider || exit 1
