# Edge-Cluster Deployment (rpi4 / rpi5 / orangepi)

| Version | Date | Status |
|---|---|---|
| 1.0.0 | 2026-08-25 | Active |

Primary deployment topology for KAE. Kaggle GPU is **opt-in fallback only**
(see [RFC 0022 v1.1.0](../architecture/0022-gpu-runner-orchestration.md)).

---

## Topology

```
┌─────────────────────────────────────────────────────┐
│                   Home LAN (192.168.88.0/24)        │
│                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │   rpi4   │   │     rpi5     │   │  orangepi   │  │
│  │ (backup) │   │  (primary)   │   │ (ollama-2)  │  │
│  │          │   │              │   │             │  │
│  │ KAE      │   │ KAE Engine   │   │ ollama      │  │
│  │ (mirror) │   │ Manager      │   │ llama3.1    │  │
│  │          │   │ ollama       │   │ qwen2.5     │  │
│  │          │   │ llama3.1     │   │             │  │
│  │          │   │ qwen2.5      │   │             │  │
│  └──────────┘   └──────────────┘   └─────────────┘  │
│   .72 (offline)  .73                .74              │
└─────────────────────────────────────────────────────┘
```

### Roles

| Host | IP | Role | Docker services |
|---|---|---|---|
| **rpi5** | 192.168.88.73 | Primary KAE engine + Manager + ollama | `kae-engine`, `kae-manager`, `ollama` |
| **orangepi** | 192.168.88.74 | Secondary ollama node | `ollama` |
| **rpi4** | 192.168.88.72 | Offline backup (KAE_ROLE=backup) | `kae-engine` (mirror) |

---

## Prerequisites

- Docker + Docker Compose on each host
- SSH keys for `rpi4`, `rpi5`, `orangepi` (see `~/.ssh/config`)
- ollama installed natively or via Docker on rpi5 + orangepi
- Models pulled: `ollama pull llama3.1 && ollama pull qwen2.5`

---

## Deploy: rpi5 (primary)

### KAE Engine

```bash
ssh rpi5
cd ~/BookAssembler
git pull origin main
docker compose up -d --build
```

### Manager

Manager runs alongside the engine. Config in `~/kae-manager/docker-compose.manager.yml`:

```yaml
services:
  kae-manager:
    image: python:3.12-slim
    working_dir: /app
    volumes:
      - ~/BookAssembler:/app:ro
      - ~/.manager:/app/.manager
    environment:
      KAE_MANAGER_PORT: "8080"
      KAE_MANAGER_BACKEND: ollama
      KAE_OLLAMA_HOST: "http://orangepi:11434"
      KAE_RUNNER_TOKEN: "${KAE_RUNNER_TOKEN}"
    command: ["python", "-m", "src.agents.manager"]
    ports:
      - "8080:8080"
    restart: unless-stopped
    extra_hosts:
      - "orangepi:192.168.88.74"
```

```bash
ssh rpi5
cd ~/kae-manager
docker compose -f docker-compose.manager.yml up -d --build
```

### ollama (rpi5)

```bash
ssh rpi5
ollama serve &  # or systemctl start ollama
ollama pull llama3.1
ollama pull qwen2.5
```

---

## Deploy: orangepi (secondary ollama)

```bash
ssh orangepi
ollama serve &  # or systemctl start ollama
ollama pull llama3.1
ollama pull qwen2.5
# Future: ollama pull llava:7b  (~4.5 GB, for vision tasks)
```

Verify from rpi5:

```bash
curl http://orangepi:11434/api/tags
```

---

## Deploy: rpi4 (backup, when online)

```bash
ssh rpi4
cd ~/BookAssembler
git pull origin main
KAE_ROLE=backup docker compose up -d --build
```

rpi4 is currently offline (since 2026-08-22). Physical inspection required.

---

## Kaggle GPU Fallback (opt-in)

For tasks exceeding edge-cluster VRAM (Qwen2.5-VL-7B inference):

```bash
KAE_MANAGER_URL='https://<manager-public-url>' \
KAE_RUNNER_TOKEN='<token>' \
  bin/push-kaggle-runner.sh

bin/poll-kaggle-runner.sh
```

See [colab/README.md](../../colab/README.md) for details.

---

## Health Checks

```bash
# KAE Engine
curl http://rpi5:8000/health

# Manager
curl http://rpi5:8080/health

# ollama (rpi5)
curl http://rpi5:11434/api/tags

# ollama (orangepi)
curl http://orangepi:11434/api/tags
```
