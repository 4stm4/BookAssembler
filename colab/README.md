# GPU-агенты для KAE (Colab / Kaggle)

Тяжёлые модели (vision-векторизация, OCR таблиц/формул) выносятся на бесплатный
GPU и подключаются как обычный агент в KAE. Три ноутбука — три пути с разным
компромиссом:

| Ноутбук | Кому | Плюсы | Минусы |
|---|---|---|---|
| **`kaggle-runner/`** (RFC 0022, managed) | Прод-путь: KAE сам будит GPU по запросу, гасит по простою | Экономит GPU-квоту, стабильный URL для KAE, аудит, метрики | Нужен Manager (`python -m src.agents.manager`) + один раз залить kernel в Kaggle |
| **`kae_multimodel_agent.ipynb`** | Быстро попробовать: один Qwen2.5-VL для table/formula/vision | Прямой путь без Manager, всё в одном ноутбуке | GPU-часы тикают всё время работы ноутбука; URL меняется на каждый рестарт |
| **`kae_got_ocr.ipynb`** | Только для таблиц — GOT-OCR2.0 даёт ~99% LaTeX `tabular` | Лучшее качество на таблицах | Специализированный, несовместим с Qwen по версии transformers → отдельный ноутбук |

**По умолчанию используй `kaggle-runner/` (managed путь).** Остальные — для точечных
задач и разработки.

---

## Запуск Kaggle Runner (RFC 0022 managed путь)

### 1. Один раз — залить kernel в свой Kaggle-аккаунт

**Что нужно:**
- Аккаунт [kaggle.com](https://kaggle.com) с активированным телефоном (`Settings → Phone verification`) — иначе GPU и Internet недоступны.
- Локально: [Kaggle API](https://www.kaggle.com/docs/api) — `pip install kaggle` в **вашем** окружении (не в KAE-репозитории — см. правило проекта «не ставить локально»).
- Kaggle-креды: `Account → Create New API Token`. Актуальный клиент
  пишет токен в **`~/.kaggle/access_token`** (`chmod 600`); старые
  версии клали `~/.kaggle/kaggle.json` — если у тебя такая, оба
  варианта работают.

**Шаги:**

```bash
# 1.1. Пропиши свой owner в kernel-metadata.json (замени REPLACE_WITH на свой username):
#      "id": "<yourname>/kae-runner"

# 1.2. В Kaggle: Settings → Add-ons → Secrets → добавь два секрета:
#      KAE_MANAGER_URL   = https://<адрес твоего Manager'а, например https://kae-mgr.example>
#      KAE_RUNNER_TOKEN  = <длинный случайный Bearer — тот же, что укажешь в Manager>

# 1.3. Первый пуш создаст приватный ноутбук с GPU + Internet:
kaggle kernels push -p colab/kaggle-runner
```

После этого в аккаунте появится приватный ноутбук `kae-runner` — больше руками ничего не трогаем; всё дальше делает Manager.

### 2. Поднять Manager (CPU, где угодно — rpi5, локальный Docker, VM)

```bash
export KAE_MANAGER_PORT=8080
export KAE_MANAGER_BACKEND=kaggle
export KAE_KAGGLE_KERNEL=<yourname>/kae-runner
export KAE_KAGGLE_KERNEL_DIR=$PWD/colab/kaggle-runner
export KAE_KAE_TOKEN=<токен KAE→Manager>
export KAE_RUNNER_TOKEN=<тот же токен, что положил в Kaggle Secrets>
export KAE_MANAGER_IDLE_TIMEOUT=900   # Runner сам погаснет через 15 мин простоя

python -m src.agents.manager
# → uvicorn на 0.0.0.0:8080; аудит в ./.manager/audit.log
```

Manager нужен онлайн-24/7 — это лёгкий CPU-процесс, GPU-квоту он не тратит.

### 3. Подключить в KAE как обычного агента

В KAE → «Менеджер агентов» → **+** →
- **host** = `https://<адрес твоего Manager'а>`
- **kind** = `managed`
- **roles** = отметь нужные (`table`, `formula`, `vision`)

Сохрани. В карточке агента появится бейдж **MANAGED** и индикатор состояния Runner:
- ⚪ **cold** — GPU выключен, стартует по первому запросу
- 🔄 **starting** — Manager попросил Kaggle поднять kernel
- 🟡 **warming** — kernel запущен, модели грузятся
- ⚡ **up** — готов принимать `/infer`
- ⏸ **stopping** / ❌ **error** — переходное/аварийное

### 4. Проверить

Просто нажми **«Агент стр.»** на любой странице документа в KAE. Первый запрос
разбудит Runner (60-180с на старт Kaggle-kernel'а + прогрев модели), дальше
работает быстро. Через 15 минут без запросов Runner **сам погаснет**
(`os._exit(0)`) — Kaggle kernel завершится, GPU-часы перестанут тикать.

### Метрики и аудит

```bash
curl https://<manager>/metrics
#   kae_gpu_seconds_used <секунд GPU сожжено> ← основной KPI
#   kae_infer_total / kae_infer_errors_total / kae_infer_task_total{task=...}
#   kae_announce_total / kae_auth_fail_total

tail -f .manager/audit.log   # hash-chained JSONL по RFC 0020
#   MANAGER_STARTED, RUNNER_ANNOUNCED, INFER_COMPLETED, AUTH_FAILED, ...
```

## Альтернатива без Manager — прямые ноутбуки

### `kae_multimodel_agent.ipynb`
Открой в Kaggle с **GPU T4×2**, Run all → в конце ячейка напечатает публичный
cloudflared-URL → добавь в KAE как **`kind=multimodel`** с ролями. GPU работает
пока открыт ноутбук.

### `kae_got_ocr.ipynb`
Аналогично, но модель GOT-OCR2.0 (лучше на таблицах). Добавляется в KAE как
**`kind=got-ocr`**.

## Ссылки

- [RFC 0022: GPU Runner Orchestration](../docs/architecture/0022-gpu-runner-orchestration.md)
- [kaggle-runner/README.md](kaggle-runner/README.md) — детали kernel-артефакта
- Код Manager/Runner: `src/agents/manager/`, `src/agents/runner/`
