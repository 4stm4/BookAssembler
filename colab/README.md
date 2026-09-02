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
| Загрузка и рендер источника | `src/agents/runner/source_fetch.py` |
| Пул моделей, выгрузка по простою | `src/agents/runner/pool.py`, `idle.py` |
| Объявление Manager'у | `src/agents/runner/announce.py` |
| Загрузчики моделей | `src/agents/runner/loaders/` |

## Как KAE присылает страницу

`POST /infer` принимает две формы:

```json
{"task": "vision", "image_b64": "…"}
{"task": "vision", "source_url": "https://…/book.pdf", "page": 3}
```

Вторая нужна из-за асимметрии каналов. На rpi5 замерено **1.7 КБ/с вверх
против 4.6 МБ/с вниз** — разница в 2700 раз, причём на публичный endpoint без
всякого туннеля, то есть узкое место сам канал. Заливка отрендеренной страницы
(~22 КБ) стоит там ~13 секунд при инференсе в 1–3 секунды: GPU простаивает,
пока хост выталкивает байты.

По ссылке вверх уходит несколько сотен байт. Документ скачивает раннер по
своему каналу и кэширует по URL — книга качается один раз на все страницы.
Обратно едет только текст, то есть в быструю сторону.

Включается флагом `"source_fetch": true` у агента в `agents.json` плюс
известный публичный URL документа. Если раннер ссылку не принял (422), KAE
откатывается на заливку картинки и запоминает отказ, чтобы не пробовать снова
на каждой странице. Таймаут отказом не считается — он про канал, а не про
возможности раннера.

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
| `KAE_RUNNER_SOURCE_CACHE` | `/kaggle/working/sources` | куда класть скачанные документы |
| `KAE_RUNNER_RENDER_DPI` | `150` | качество рендера для запросов по ссылке |
| `KAE_RUNNER_FETCH_TIMEOUT` | `120` | секунд на скачивание документа |
| `KAE_RUNNER_MAX_SOURCE_BYTES` | `512 МБ` | предел размера документа |

## Проверка

```bash
curl -s $RUNNER_URL/health
# {"status":"ok","kind":"runner","tasks":[...],"ready":true}

curl -s -X POST $RUNNER_URL/infer \
  -H "Authorization: Bearer $KAE_RUNNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"task":"vision","source_url":"https://example.org/book.pdf","page":0,
       "prompt":"Reply OK"}'
```

`422` в ответ означает, что документ не скачался или страница вне диапазона —
текст ошибки в поле `detail`.

## Безопасность

URL приходит по сети, поэтому раннер принимает только `http`/`https` и
отказывается ходить на loopback, приватные и link-local адреса: иначе вызывающая
сторона могла бы читать через раннер его собственную сеть. Размер документа
ограничен, недокачанный файл в кэше не остаётся.
