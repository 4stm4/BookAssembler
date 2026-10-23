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

# RFC 0012 §3.3: XeLaTeX toolchain for target-document assembly (Cyrillic-capable).
# fonts-texgyre adds TeX Gyre Termes/Heros/Cursor - metric-compatible OTF
# clones of Times/Helvetica/Courier - so a Latin-only cell whose source was
# actually set in one of those (common in scanned technical books) can
# render in a font close to the source's own, instead of DejaVu Serif or
# Latin Modern Roman (neither is a Times/Helvetica/Courier match). DejaVu
# stays the document's main font for Cyrillic; TeX Gyre is Latin-only too
# (same gap Latin Modern has), selected per-cell in latex_builder.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-xetex texlive-latex-recommended texlive-latex-extra \
    texlive-lang-cyrillic texlive-fonts-recommended fonts-dejavu \
    fonts-texgyre && \
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

RUN mkdir -p /data/ssd

ENV NODE_ENV=production
ENV PYTHONPATH=/app
ENV KAE_SSD_PATH=/data/ssd
# CMD below already runs uvicorn; stop server.ts from racing it for port 8000.
ENV KAE_SPAWN_BACKEND=0

EXPOSE 3000
EXPOSE 8000

CMD ["sh", "-c", "python3 -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 & node dist/server.cjs"]
