FROM node:22-bookworm-slim AS frontend

WORKDIR /app
# npm ci installs what package-lock.json pins; npm reads no bun.lock, and
# `npm install` without the lock resolved the ranges afresh on every build.
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json server.ts ./
COPY src/ src/
# The UI (dist/) and the gateway (dist/server.cjs), as `npm run build` makes
# them: here, where esbuild - a dev dependency - is installed at its pin.
RUN npm run build


FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# RFC 0012 §3.3: XeLaTeX toolchain for target-document assembly
# (Cyrillic-capable), each package at its version - tex-packages.txt, which
# the e2e job of CI installs too, on this same Debian.
COPY tex-packages.txt /tmp/
RUN apt-get update && grep -v '^#' /tmp/tex-packages.txt | \
    xargs apt-get install -y --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src/ src/
# Skill packs (RFC 0006): the API loads skills/*.yaml from the working directory.
COPY skills/ skills/
COPY --from=frontend /app/dist dist/
COPY bin/docker-entrypoint.sh bin/

RUN mkdir -p /data/ssd

ENV NODE_ENV=production
ENV PYTHONPATH=/app
ENV KAE_SSD_PATH=/data/ssd
# The entrypoint runs uvicorn; stop server.ts from racing it for port 8000.
ENV KAE_SPAWN_BACKEND=0

EXPOSE 3000
EXPOSE 8000

# Both servers, each stopping the container when it stops (see the script).
CMD ["bash", "bin/docker-entrypoint.sh"]
