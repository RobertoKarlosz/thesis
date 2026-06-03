# syntax=docker/dockerfile:1
FROM pqc-base:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    stunnel4 gettext-base python3 python3-pip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY stunnel.conf.template /etc/stunnel/stunnel.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /var/lib/prometheus /var/log/stunnel /run/stunnel

EXPOSE 1883 9101

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -sf http://localhost:9101/metrics | grep -q 'handshake_latency_ms' || exit 1

ENTRYPOINT ["/entrypoint.sh"]
