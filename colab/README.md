# Kaggle GPU Runner

Ноутбук, который поднимает RFC 0022 Runner на Kaggle с GPU. Нужен там, где
vision-инференс не сделать локально: на ARM-хостах кластера (rpi5/orangepi)
одна страница через CPU занимает минуты.

```
colab/kaggle-runner/
  runner.ipynb           обёртка: окружение, туннель, запуск
  kernel-metadata.json   метаданные для `kaggle kernels push`
  README.md              как запускать и как проверить
```

## Логика живёт в репозитории, не в блокноте

Блокнот клонирует BookAssembler и запускает `python -m src.agents.runner`.
Всё поведение — в `src/agents/runner/`. Значит правка раннера не требует
трогать блокнот: следующий запуск подхватит её сам.

| Что | Где |
|---|---|
| HTTP-эндпоинты | `src/agents/runner/app.py` |
| Пул моделей, выгрузка по простою | `src/agents/runner/pool.py`, `idle.py` |
| Объявление Manager'у | `src/agents/runner/announce.py` |
| Загрузчики моделей | `src/agents/runner/loaders/` |

## Контракт

`POST /infer` — `{"task": "vision", "image_b64": "…"}` → `{"text": "…"}`,
как задано RFC 0022 §4.2. Раннер модель только исполняет; страницу рендерит и
присылает вызывающая сторона.

Замер на Qwen2.5-VL: страница 512 px отвечает за ~1.7 с, 900 px не ответила за
180 с. Стоимость растёт с числом визуальных токенов, а передача 8 КБ при
~300 КБ/с занимает миллисекунды — то есть ограничивает GPU, не канал. Размер
картинки задаётся на стороне KAE (`KAE_VISION_DPI`, `_JPEG_QUALITY`,
`_MAX_DIM`) и поднимается только против замера на целевой карте.

## Запуск

```bash
export KAE_MANAGER_URL=https://your-manager
export KAE_RUNNER_TOKEN=...
bin/push-kaggle-runner.sh      # подставит секреты и сделает push
bin/poll-kaggle-runner.sh      # дождётся публичного URL из логов
```

Скрипт подставляет секреты вместо плейсхолдеров на push-time, поэтому в git
они не попадают. При ручном запуске в UI значения читаются из Kaggle Secrets
(`KAE_MANAGER_URL`, `KAE_RUNNER_TOKEN`).

Из вывода ячейки 4 взять строку `Runner will announce as: https://…` и
прописать этот host агенту в `agents.json`.

## Переменные окружения

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `KAE_RUNNER_LOADERS` | `qwen25vl` | какие загрузчики регистрировать |
| `KAE_RUNNER_IDLE_TIMEOUT` | `900` | секунд простоя до выхода |

## Проверка

```bash
curl -s $RUNNER_URL/health
# {"status":"ok","kind":"runner","tasks":[...],"ready":true}

curl -s -X POST $RUNNER_URL/infer \
  -H "Authorization: Bearer $KAE_RUNNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"task":"vision","image_b64":"<base64 PNG>","prompt":"Reply OK"}'
```
