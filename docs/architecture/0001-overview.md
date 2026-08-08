# RFC 0001: Overview & Vision

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Введение и позиционирование

### 1.1. Проблема
Традиционные инструменты конвертации документов (PDF-парсеры, OCR-системы, Markdown-конвертеры) проектируются под парадигму «Документ в Текст». В этой парадигме теряется до 80% контекста:
- Уничтожаются структурные и семантические связи (ссылки вида «см. рис. 5», соответствие таблиц сноскам, связки «мнемоника — описание операндов»).
- Границы чанков при нарезке под RAG задаются фиксированным числом символов или токенов, что приводит к разрыву логических контекстов (формул, таблиц, листингов кода).
- Архитектура жестко связывается с конкретным входным форматом (обычно PDF) или библиотекой визуального разбора (PyMuPDF, PDFMiner, Tesseract).

### 1.2. Решение: Knowledge Assembly Engine (KAE)
Knowledge Assembly Engine (KAE) — это универсальная платформа сборки, семантического анализа и структурирования знаний из неструктурированных и полуструктурированных источников.

KAE меняет целевой артефакт обработки:
- **Вместо:** PDF → Plain Text / Markdown
- **KAE делает:** Unstructured Source → Knowledge Representation Model (KRM) → AI Knowledge Base + Multi-Format Artifacts

Платформа превращает входной поток в насыщенное представлением знаний дерево с графовыми слоями (Knowledge Graph, Reading Graph), из которого синхронно выстраиваются как представлимые человеком документы (Markdown, LaTeX, EPUB, HTML), так и машиночитаемые AI-слои (RAG Chunks, Embeddings Manifest, Fine-Tuning Datasets).

## 2. Архитектурные принципы
1. **Контракты превыше кода (Contracts First):** Код анализаторов и трансформаций не пишется без предварительного описания типов, матриц разрешений и границ изменений в RFC.
2. **Изоляция источника (Source Agnosticism):** Ни один модуль системы, за исключением `SourceAdapter`, не знает о природе исходного файла (PDF, DOCX, HTML, Jupyter Notebook, Git-репозиторий).
3. **Иммутабельность идентичности (Identity Preservation):** Каждый элемент контента получает уникальный глобальный UUIDv4 в момент первичного извлечения. Идентификатор не меняется при любых трансформациях, нормализациях или переносах между структурами.
4. **Запрет на неявные удаления (No Silent Deletions):** Анализаторам запрещено удалять узлы из базовой модели. Допускается только пометка узла (`is_tombstoned = True`) с указанием причины или исключение из графа чтения.
5. **Многослойность представления (Decoupled Layer Architecture):** Физическая геометрия (верстка), структура (иерархия), порядок чтения (DAG) и семантические связи хранятся в отдельных изолированных слоях.

## 3. Границы системы (System Boundaries)

```
                       [ SOURCE LAYER ]
 (PDF, DOCX, HTML, Wiki, Markdown, Git Repositories, Jupyter)
                              │
                              ▼
                     [ Source Adapters ]
                              │
                              ▼
           [ Knowledge Representation Model (KRM) ]
                    (Unprocessed State)
                              │
                              ▼
                 [ Milestone -0.5: Normalization ]
    (Unicode, Ligatures, Geometry Normalization, Coordinate Grid)
                              │
                              ▼
                 [ Analyzer Pipeline Engine ]
      ┌───────────────────────┴───────────────────────┐
      ▼                                               ▼
[ Structural Analyzers ]                    [ Semantic Analyzers ]
(Layout, Reading Graph)                     (Tables, Code, Figures)
      │                                               │
      └───────────────────────┬───────────────────────┘
                              │ ◄── [ Skills Engine ]
                              │     (Intel, IEEE, Microsoft, etc.)
                              ▼
                  [ Knowledge Graph Builder ]
           (Cross-References, Semantic Units, Entities)
                              │
                              ▼
               [ Quality & Benchmark Control ]
                              │
      ┌───────────────────────┴───────────────────────┐
      ▼                                               ▼
[ Human Layer ]                             [ Machine & AI Layer ]
(LaTeX, Markdown,                           (KRM JSON, Chunk Tree, 
 EPUB, HTML)                                 Knowledge Graph, RAG Index)
```

### 3.1. Inbound Boundary (Входная граница)
- Принимает сырые данные через `SourceAdapter.parse()`.
- Возвращает первичный `KnowledgeDocument` в неотрисованном/необработанном состоянии (`Unprocessed KRM`).
- Никакая специфика парсинга (байты PDF, DOM HTML, XML-дерево OpenXML) не протекает за пределы адаптера.

### 3.2. Processing Core (Ядро обработки)
- Построено на последовательном запуске конвейера `BaseAnalyzer`.
- Анализаторы обогащают KRM, строят `ReadingGraph` и добавляют связи в `KnowledgeGraph`.
- Поведение анализаторов может корректироваться внешними декларативными модулями — `Skills`.

### 3.3. Outbound Boundary (Выходная граница)
- Экспортеры читают полностью размеченный и валидированный `KnowledgeDocument`.
- Генерация финальных представлений (Markdown, LaTeX, RAG JSON) происходит без повторного анализа исходных файлов.

## 4. Карта документов RFC
Система спецификаций KAE состоит из 10 базовых RFC:
- **RFC 0001: Overview & Vision** (текущий документ) — концепция, границы и архитектурные принципы KAE.
- **RFC 0002: Knowledge Representation Model (KRM)** — спецификация классов данных, слоев представления и семантики.
- **RFC 0003: Knowledge Graph Specification** — граф связей, сущности, типы рёбер, cross-references.
- **RFC 0004: Reading Graph Specification** — модель направленного ациклического графа (DAG) для мультитрекового порядка чтения.
- **RFC 0005: Analyzer API & Permissions Matrix** — контракты анализаторов, интерфейсы, матрица прав доступа.
- **RFC 0006: Skills & Recipes Specification** — декларативные навыки, рецепты конвейера и профили источников.
- **RFC 0007: AI Knowledge Layer & Chunking** — семантический чанкинг, хлебные крошки, форматы экспорта для RAG/LLM.
- **RFC 0008: Source Adapters Architecture** — спецификация адаптеров (PDF, DOCX, HTML, Repo, Notebook).
- **RFC 0009: Benchmark & Corpus Specification** — метрики качества (TEDS, WER, Link Recall), состав эталонного корпуса `tests/benchmark/`.
- **RFC 0010: Plugin API & Sandbox Execution** — система внешних плагинов, изоляция выполнения и версионирование.
