FROM node:22-bookworm-slim AS frontend

WORKDIR /app
COPY package.json bun.lock ./
RUN npm install
COPY index.html vite.config.ts tsconfig.json ./
COPY src/ src/
RUN npx vite build


FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# RFC 0012 §3.3: XeLaTeX toolchain for target-document assembly (Cyrillic-capable).
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-xetex texlive-latex-recommended texlive-lang-cyrillic \
    texlive-fonts-recommended fonts-dejavu && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json bun.lock ./
RUN npm install --omit=dev

COPY server.ts tsconfig.json ./
COPY src/ src/
COPY --from=frontend /app/dist dist/

RUN npx esbuild server.ts --bundle --platform=node --format=cjs \
    --packages=external --sourcemap --outfile=dist/server.cjs

RUN mkdir -p /data/ssd

ENV NODE_ENV=production
ENV PYTHONPATH=/app
ENV KAE_SSD_PATH=/data/ssd

EXPOSE 3000
EXPOSE 8000

CMD ["sh", "-c", "python3 -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 & node dist/server.cjs"]
