# BookAssembler — автоматический перевод технических книг

Пайплайн для перевода отсканированных PDF-книг в печатный LaTeX на русском языке.
Разработан для *"The 8088 and 8086 Microprocessors"* (Triebel & Singh), но архитектура универсальна.

## Быстрый старт

```bash
# Python >= 3.13 обязателен (зависимость pyjobkit)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"

# Скопировать конфиг
cp .env.example .env

# Собрать Docker-образ для компиляции LaTeX
docker build -t bookassembler-xelatex .

# Запустить пайплайн для главы 5
python3 src/pipeline.py --chapter 5

# Продолжить после ошибки
python3 src/pipeline.py --chapter 5 --resume

# Проверить статус
python3 src/pipeline.py --chapter 5 --status

# pyjobkit — очередь задач
python3 src/pipeline.py --chapter 5 --enqueue        # поставить в очередь
python3 src/pipeline.py --work-once                   # выполнить и выйти
python3 src/pipeline.py --work                        # worker (long-running)
python3 src/pipeline.py --chapter 5 --jobs-status     # статус задач
```

## Архитектура

```
PDF (скан) → extract → manifest → figures → translate → autofix → validate → build → compile → PDF
```

### Конфигурация

Вся конфигурация вынесена из кода:

| Файл | Что настраивает |
|------|----------------|
| `chapters.yaml` | Структура книги: главы, диапазоны страниц, PDF-файл |
| `.env` | Режим перевода, режим компиляции, ключи API |
| `glossary.json` | Словарь терминов (EN→RU), keep-as-is списки, правила форматирования |

```bash
# .env
TRANSLATE_MODE=api          # "api" (автоматический) или "agent" (задачи для Claude Code)
ANTHROPIC_API_KEY=sk-...    # только для TRANSLATE_MODE=api
COMPILE_MODE=docker         # "docker" (локально) или "ssh" (удалённый хост)
COMPILE_HOST=user@host      # только для COMPILE_MODE=ssh
COMPILE_DIR=~/path/to/dir   # только для COMPILE_MODE=ssh
```

## Стадии пайплайна

| # | Стадия | Что делает | Блокирует следующую? |
|---|--------|-----------|---------------------|
| 1 | `extract` | Извлекает текст из PDF (PyMuPDF) | — |
| 2 | `manifest` | Строит инвентарь: фигуры, примеры, DEBUG-сессии, порядок элементов | — |
| 3 | `figures` | Рендерит страницы, анализирует фигуры (с per-figure кешем), генерирует TikZ-задачи | — |
| 4 | `translate` | Переводит через Claude API (с retry) или генерирует задачи для агентов | — |
| 5 | `autofix` | Wrap DEBUG/ASM в code blocks, удаление дублей таблиц, fix подстрочных | — |
| 6 | `validate` | Проверка по манифесту + глоссарию. **Блокирует build при ошибках** | build |
| 7 | `build` | Собирает LaTeX из переводов (markdown → LaTeX, вставка фигур) | — |
| 8 | `compile` | Компиляция XeLaTeX через Docker или SSH | — |

### State management

Каждый этап трекается в `cache/state/ch{N}.json`:
- **Чекпоинты** — при сбое на 400-й странице, 399 уже сохранены
- **Resume** — `--resume` продолжает с последнего упавшего этапа
- **Зависимости** — build не запустится без validate, translate не запустится без extract
- **Сброс** — `--reset-stage translate` для повторного запуска отдельного этапа

```bash
python3 src/pipeline.py --chapter 5 --status
# Глава 5:
#   [+] extract: done (3с)
#   [+] manifest: done (12с)
#   [+] translate: done (180с)
#   [!!] validate: failed — 12 проблем
```

## Перевод

### Два режима

**API-режим** (`TRANSLATE_MODE=api`) — полностью автоматический:
- Прямые вызовы Claude API с контекстными промптами
- Exponential backoff при ошибках (до `TRANSLATE_MAX_RETRIES` попыток)
- Встроенная валидация каждой страницы

**Agent-режим** (`TRANSLATE_MODE=agent`) — генерирует задачи:
- Записывает задачи в `ch{N}_tasks.json` с метаданными (тип контента, глоссарий)
- Задачи выполняются через Claude Code Agent tool

### Merge-стратегия переводов

Переводы загружаются слоями с чётким приоритетом:

```
ch4_154_169.json      ← 1. оригинальный перевод (низший приоритет)
ch4_autofix.json      ← 2. автоматические исправления (diff-слой)
ch4_all_fixed.json    ← 3. ручные правки (высший приоритет, никогда не затираются)
```

### Живой глоссарий

При валидации перевода система автоматически находит технические термины, отсутствующие в `glossary.json`, и записывает их в `glossary_suggestions.json` с счётчиком упоминаний. Разбор предложений — вручную.

## Скрипты

| Скрипт | Назначение |
|--------|-----------|
| `pipeline.py` | Главный вход — оркестрация всех стадий |
| `translator.py` | Абстракция перевода: `TranslatorClient`, контракты данных, валидация |
| `state.py` | State management: чекпоинты, зависимости, resume |
| `extract_chapter_manifest.py` | Инвентарь главы из оригинального PDF |
| `validate_chapter.py` | Валидация перевода (11 категорий проверок) |
| `build_latex.py` | Markdown → LaTeX (заголовки, списки, таблицы, код, примеры, фигуры) |
| `generate_figures.py` | Поиск фигур в PDF, рендер страниц, промпты для TikZ-агентов |
| `translate_book.py` | Утилиты извлечения текста и генерации промптов |
| `diagram_extract.py` | CV-анализ схем: crop → classify → detect → measure → topology → review |

## Структура данных

| Путь | Содержимое | В Git? |
|------|-----------|--------|
| `chapters.yaml` | Структура книги | Да |
| `glossary.json` | Словарь терминов | Да |
| `src/` | Скрипты | Да |
| `cache/text/` | Извлечённый текст | Нет |
| `cache/state/` | Состояние пайплайна | Нет |
| `cache/diagram_analysis/` | Кеш анализа фигур | Нет |
| `claude_translations/` | JSON с переводами | Нет |
| `figures/` | TikZ `.tex` файлы | Нет |
| `latex_output/` | Готовые `.tex` для компиляции | Нет |
| `glossary_suggestions.json` | Предложения для глоссария | Нет |

## Компиляция LaTeX

### Docker (по умолчанию)

```bash
docker build -t bookassembler-xelatex .
python3 src/pipeline.py --chapter 5 --stage compile
```

Образ содержит XeLaTeX, кириллические шрифты и все необходимые пакеты.

### SSH (опционально)

Для компиляции на удалённом хосте установите в `.env`:

```bash
COMPILE_MODE=ssh
COMPILE_HOST=user@hostname
COMPILE_DIR=~/path/to/latex
```

SSH-режим блокируется в CI/CD-окружении. Перед подключением проверяется доступность хоста и наличие SSH-ключей.

## pyjobkit — очередь задач

Тяжёлые стадии (translate, figures, build, compile) можно выполнять через очередь `pyjobkit` с SQLite-бэкендом:

```bash
# Поставить задачи для главы 5 в очередь
python3 src/pipeline.py --chapter 5 --enqueue

# Выполнить все задачи в очереди и завершиться
python3 src/pipeline.py --work-once

# Или запустить worker для постоянной обработки
python3 src/pipeline.py --work

# Посмотреть статус задач
python3 src/pipeline.py --chapter 5 --jobs-status
```

База задач: `cache/jobs/bookassembler.sqlite3` (переопределяется через `BOOKASSEMBLER_JOB_DSN`).

Идемпотентность: повторный `--enqueue` для той же главы не дублирует задачи (ключи вида `ch5:translate:218-300`).

## Зависимости

- Python >= 3.13
- PyMuPDF (`pymupdf`)
- OpenCV (`opencv-python-headless`)
- NumPy (`numpy`)
- PyYAML (`pyyaml`) — опционально, для `chapters.yaml`
- pyjobkit[sqlite] (`pyjobkit`) — очередь задач с SQLite-бэкендом
- Anthropic SDK (`anthropic`) — только для `TRANSLATE_MODE=api`
- Docker — для локальной компиляции LaTeX
