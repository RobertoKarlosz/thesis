# syntax=docker/dockerfile:1
FROM pqc-base:latest

ENV DEBIAN_FRONTEND=noninteractive

# mosquitto: egyszerű MQTT bróker (a TLS-t a mellette futó stunnel folyamat zárja le)
# stunnel4: PQC-TLS szerver a 8883-as porton → sima forgalmat továbbít a mosquitto:1883-ra
RUN apt-get update && apt-get install -y --no-install-recommends \
    mosquitto \
    mosquitto-clients \
    stunnel4 \
    gettext-base \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/lib/mosquitto /var/log/mosquitto /var/run/mosquitto /run/stunnel && \
    chown -R mosquitto:mosquitto /var/lib/mosquitto /var/log/mosquitto /var/run/mosquitto 2>/dev/null || true

COPY mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY stunnel-server.conf.template /etc/stunnel/stunnel-server.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8883

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD mosquitto_pub -h 127.0.0.1 -p 1883 -t '$SYS/broker/version' -m '' -q 0 2>/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
