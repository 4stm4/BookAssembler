# Система автоматического перевода книг

Набор скриптов для перевода технических PDF-книг (сканов) в печатный LaTeX на русском языке.
Разработано для книги *"The 8088 and 8086 Microprocessors"* (Triebel & Singh), но архитектура универсальна.

## Архитектура

```
PDF (скан) → extract → manifest → figures → translate → autofix → validate → build → compile → PDF (печать)
```

Все скрипты работают из корня проекта. Данные лежат в корне, скрипты — в `src/`.

## Скрипты

### pipeline.py — главный вход

Единая точка запуска всех стадий. Знает границы всех 14 глав.

```bash
# Полный пайплайн для главы:
python3 src/pipeline.py --chapter 5

# Отдельная стадия:
python3 src/pipeline.py --chapter 4 --stage validate

# Список глав:
python3 src/pipeline.py --list
```

**9 стадий:**

| # | Стадия | Что делает | Автоматически? |
|---|--------|-----------|----------------|
| 1 | `extract` | Извлекает текст из PDF (PyMuPDF) | Да |
| 2 | `manifest` | Строит инвентарь: фигуры, примеры, DEBUG, порядок элементов | Да |
| 3 | `figures` | Рендерит страницы с фигурами, генерирует задачи для TikZ-агентов | Да (задачи) |
| 4 | `translate` | Генерирует задачи для агентов-переводчиков (с глоссарием) | Да (задачи) |
| 5 | `agents` | Показывает задачи из `ch{N}_tasks.json` для Claude Code Agent tool | Нет — запуск агентов вручную |
| 6 | `autofix` | Чинит: naked DEBUG → code blocks, дубли таблиц, подстрочные индексы | Да |
| 7 | `validate` | Проверяет перевод по манифесту + глоссарию | Да |
| 8 | `build` | Собирает LaTeX из переведённого JSON | Да |
| 9 | `compile` | rsync на RPi5 + xelatex | Да |

### extract_chapter_manifest.py — инвентарь главы

Строит ground truth из оригинального PDF: разделы, фигуры (с типами и порядком), примеры, DEBUG-сессии, нумерованные списки.

```bash
python3 src/extract_chapter_manifest.py -i book.pdf -c 4 -s 154 -e 217 -j ch4_manifest.json
```

Выход — `ch{N}_manifest.json` с полями:
- `sections` — разделы с номерами и заголовками
- `figures` — фигуры с типами (debug_session, source_listing, register_diagram, ...)
- `examples` — все EXAMPLE X.Y
- `debug_sessions` — страницы с DEBUG
- `element_order` — порядок элементов на каждой странице

### validate_chapter.py — валидатор

Проверяет перевод по 11 категориям:

- Непереведённый текст (EXAMPLE, Figure, Solution, ...)
- Мусор/артефакты (_16, ⊠)
- Проблемные Unicode-символы
- Отсутствующие таблицы
- Кривые таблицы (пустые ячейки, неправильные заголовки)
- Дублирование markdown-таблиц с TikZ
- Нумерованные списки, превращённые в буллеты
- Код вне code blocks
- Разбитые DEBUG-сессии
- Примеры
- Глоссарий (ключевые термины переведены)
- Манифест (все элементы на месте)

```bash
python3 src/validate_chapter.py -p ch4 -s 154 -e 217 -m ch4_manifest.json
```

### build_latex.py — сборка LaTeX

Конвертирует JSON с переводами в `.tex`. Обрабатывает:
- Markdown → LaTeX (заголовки, списки, таблицы, код)
- examplebox окружения для примеров
- Автовставка `\input{figures/fig_X_Y}` по ссылкам в тексте
- Unicode подстрочные → LaTeX `$_{...}$`
- Стрелки → LaTeX math
- DEBUG-сессии → lstlisting[style=debug]

```bash
python3 src/build_latex.py -c 4 -s 154 -e 217
```

### generate_figures.py — генерация TikZ-фигур

Сканирует PDF на предмет фигур, рендерит страницы как PNG, генерирует промпты для агентов.

```bash
python3 src/generate_figures.py -i book.pdf -c 4 -s 154 -e 217 --render
python3 src/generate_figures.py -i book.pdf -c 4 -s 154 -e 217 --validate
```

### translate_book.py — утилиты перевода

Извлечение текста, генерация промптов для агентов с глоссарием.

```bash
python3 src/translate_book.py -i book.pdf -c 4 -s extract
```

## Данные

| Путь | Содержимое |
|------|-----------|
| `glossary.json` | Словарь терминов (EN→RU) + keep-as-is списки + правила форматирования |
| `ch{N}_manifest.json` | Инвентарь главы (ground truth) |
| `ch{N}_tasks.json` | Задачи для агентов (перевод + TikZ) |
| `cache/text/` | Извлечённый текст из PDF |
| `claude_translations/` | JSON с переводами (оригинал + _fixed + _autofix) |
| `figures/` | TikZ `.tex` файлы фигур |
| `latex_output/` | Готовые `.tex` файлы для компиляции |
| `latex_output/book.tex` | Главный файл LaTeX (шрифты, пакеты, стили) |

## Приоритет файлов переводов

```
ch4_154_169.json          ← оригинальный перевод агента
ch4_all_fixed.json        ← ручные правки (перезаписывает)
ch4_autofix.json          ← автоматические правки (перезаписывает)
```

Поздние файлы перезаписывают ранние по ключу страницы.

### diagram_extract.py — извлечение и анализ схем

Вырезает фигуры из PDF, определяет тип (схема/таблица/фото/код), находит примитивы и их координаты.

```bash
# Анализ одной фигуры с debug-картинками:
python3 src/diagram_extract.py -i book.pdf --page 174 --figure 4.10 --debug

# Анализ всех фигур главы:
python3 src/diagram_extract.py -i book.pdf -c 4 -s 154 -e 217 --debug
```

**Пайплайн:**
1. **crop** — вырезка по caption + горизонтальным разделителям
2. **classify** — diagram/table/photo/code по гистограмме, линиям, плотности текста
3. **detect** — примитивы через adaptive threshold + контуры + HoughLinesP
4. **measure** — bbox, center, размеры в pt для каждого примитива
5. **topology** — кто с кем соединён (endpoints стрелок → ближайшие rect'ы)
6. **review** — что передать агенту (low confidence, missing arrows, overlaps)

**Примитивы:** rect, line, arrow, text, ellipse, unknown
**Debug-выход:** `debug_diagrams/fig_X_Y_crop.png`, `_annotated.png`, `_analysis.json`

## Зависимости

- Python 3.10+
- PyMuPDF (`pip install pymupdf`)
- OpenCV (`pip install opencv-python-headless`)
- NumPy (`pip install numpy`)
- XeLaTeX на RPi5 (192.168.88.71) с пакетами: fontspec, polyglossia, tikz, listings, mdframed
- Шрифты: Noto Serif, Noto Sans, DejaVu Sans Mono

## Компиляция

LaTeX компилируется на RPi5 через SSH:

```bash
rsync -az latex_output/ alex@192.168.88.71:~/micro8086_translate/latex_output/
rsync -az figures/ alex@192.168.88.71:~/micro8086_translate/latex_output/figures/
ssh alex@192.168.88.71 'cd ~/micro8086_translate/latex_output && xelatex -interaction=nonstopmode book.tex'
```
