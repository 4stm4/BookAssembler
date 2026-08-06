FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-xetex \
    texlive-lang-cyrillic \
    texlive-fonts-extra \
    texlive-latex-extra \
    texlive-science \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
