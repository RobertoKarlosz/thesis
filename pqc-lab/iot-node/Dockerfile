# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY node.py .

EXPOSE 9100

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:9100/metrics')" || exit 1

CMD ["python3", "-u", "node.py"]
