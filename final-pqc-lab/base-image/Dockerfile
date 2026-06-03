# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build libssl-dev python3-dev \
    git curl astyle pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch main https://github.com/open-quantum-safe/liboqs.git
WORKDIR /build/liboqs/build
RUN cmake .. -GNinja \
    -DOQS_DIST_BUILD=ON -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local -DOQS_USE_OPENSSL=ON \
    && ninja -j$(nproc) && ninja install && ldconfig

WORKDIR /build
RUN git clone --depth 1 https://github.com/open-quantum-safe/oqs-provider.git
WORKDIR /build/oqs-provider
RUN cmake -S . -B build -GNinja \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -Dliboqs_DIR=/usr/local/lib/cmake/liboqs \
    -DOPENSSL_MODULES_PATH=/usr/local/lib/ossl-modules \
    && cmake --build build -j$(nproc) && cmake --install build

RUN mkdir -p /usr/local/lib/ossl-modules && \
    find / -maxdepth 12 -name 'oqsprovider.so' 2>/dev/null \
        ! -path '/usr/local/lib/ossl-modules/oqsprovider.so' \
        -exec cp -v {} /usr/local/lib/ossl-modules/ \; && \
    ls -la /usr/local/lib/ossl-modules/

# ── Final image ───────────────────────────────────────────────────────────────
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 openssl ca-certificates python3 python3-pip curl binutils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/ /usr/local/

RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/usr-local.conf && ldconfig

# Standalone OpenSSL config that activates oqsprovider + PQC TLS groups.
# Ubuntu 24.04's system openssl.cnf has openssl_conf commented out,
# so we own the config completely via OPENSSL_CONF.
RUN cat > /etc/ssl/oqs-openssl.cnf <<'EOF'
openssl_conf = openssl_init

[openssl_init]
providers = provider_sect
ssl_conf = ssl_sect

[ssl_sect]
system_default = tls_system_default

[tls_system_default]
Groups = mlkem768:X25519MLKEM768:bikel1:bikel3:bikel5:x25519:P-256:P-384:P-521

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

RUN openssl list -providers | grep -q oqsprovider && \
    echo "oqsprovider loaded OK" || \
    { echo "ERROR: oqsprovider failed to load"; openssl list -providers; exit 1; }

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD openssl list -providers | grep -q oqsprovider || exit 1
