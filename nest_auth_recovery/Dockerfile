FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv chromium xvfb x11vnc novnc ca-certificates fonts-liberation util-linux procps && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/recovery \
    && /opt/recovery/bin/pip install --no-cache-dir aiohttp==3.12.15 playwright==1.55.0 \
    && useradd -m -u 10001 browser
WORKDIR /app
COPY recovery.py index.html /app/
CMD ["/opt/recovery/bin/python", "/app/recovery.py"]
