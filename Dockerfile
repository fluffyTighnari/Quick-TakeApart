# syntax=docker/dockerfile:1

# Build the Vite frontend first.
FROM node:22-bookworm-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Runtime needs Node for pyright, plus Python for the server.
FROM node:22-bookworm-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    QTA_SETTINGS_PATH=/data/settings.json

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# pyright and its assets are runtime dependencies of the indexer.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY engine ./engine
COPY serve.py README.md ./
COPY --from=web-build /app/web/dist ./web/dist

RUN mkdir -p /data /workspace
VOLUME ["/data"]
EXPOSE 7741

CMD ["python3", "serve.py", "/workspace", "--host", "0.0.0.0", "--port", "7741"]
