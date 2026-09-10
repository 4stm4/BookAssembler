# Knowledge Assembly Engine (KAE)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React">
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

**Knowledge Assembly Engine (KAE)** превращает неструктурированные документы (в первую
очередь PDF-сканы технических книг и даташитов) в структурированную **Knowledge
Representation Model (KRM)** — дерево типизированных блоков с графами связей, из
которого можно строить переводы и целевые документы.

Вместо парадигмы «PDF → плоский текст» KAE сохраняет структуру: заголовки, таблицы,
подписи, схемы, титульные страницы, порядок чтения и семантические связи — с
привязкой каждого блока к координатам на странице.

Архитектура описана в наборе RFC (`docs/architecture/`, [аудит соответствия
кода](docs/architecture/COMPLIANCE_AUDIT.md)).

---

## Возможности

| Область | Что реализовано | Статус |
|---|---|---|
| **Извлечение (PDF)** | `PdfSourceAdapter` на PyMuPDF: блоки, стиль, bbox, фильтр OCR-мусора | ✅ |
| **Пайплайн анализа** | 22 анализатора: нормализация, порядок чтения, эфемера, схемы, заголовки, списки, формулы, теоремы, определения, callout, сноски, библиография, алгоритмы, указатель, титул, таблицы, подписи, page-agent, классификация, LLM-уточнение, сущности, proper nouns, цитаты | ✅ |
| **Графы** | Knowledge Graph (сущности/связи) + Reading Graph (DAG порядка чтения) | ✅ |
| **KRM round-trip** | Сохранение bbox+стиля+перевода в JSON, восстановление без потерь (RFC 0002/0011) | ✅ |
| **HITL** | Баннер low-confidence узлов, ручная правка, агент-уточнение отдельного блока | ✅ |
| **Агент на страницу** | Переклассификация и **пересборка** страницы по роли (титул/схема/таблица) | ✅ |
| **Менеджер агентов** | Несколько хостов (ollama/GOT-OCR/multimodel/Colab/Kaggle), **роли** (translate/refine/table/vision/formula), роутинг задач по ролям | ✅ |
| **GPU-агенты (Colab/Kaggle)** | Мультимодельный агент на Qwen2.5-VL (2×T4 fp16, шардинг), GOT-OCR2.0 отдельно; вызывается через `/infer?task=` | ✅ |
| **Распознавание таблиц** | Автовызов vision-агента на table-страницы → чистый LaTeX `tabular` в `TableBlock` (проверено на PDP-11) | ✅ |
| **Перевод** | Постраничный фоновый перевод через ollama; источник не мутируется, lineage (RFC 0021) | ✅ |
| **Сборка книги** | XeLaTeX в Docker (кириллица) + `kae.lock`/`book.json` + `.kap` bundle (RFC 0012/0013) | ✅ |
| **Векторизация схем** | Скан-схема → TikZ: CV (OpenCV) + vision-LLM (RFC 0011 `tikz_vectorization`) | 🧪 эксперим. |
| **GPU Runner-оркестрация** | Двухуровневый агент (Manager+Runner) для on-demand GPU и экономии Kaggle-квоты (RFC 0022): `src/agents/{manager,runner}` + KaggleKernelBackend + UI `kind=managed`; 80 unit-тестов | ✅ |
| **Skills Engine** | DSL-движок для skill pack'ов (YAML): фильтрация пайплайна по типу документа, 3 пака (pdp11, pdf-lit, math-book) | ✅ |
| **Plugin API** | Ed25519-подпись, guarded proxy с проверкой прав, реестр плагинов (RFC 0010) | ✅ |
| **Contract Testing** | Идемпотентность анализаторов (RFC 0014) + битовый детерминизм LaTeX (RFC 0009), 25 контрактных тестов | ✅ |
| **Vision Router** | Ollama vision-модели (llava) на edge-кластере, роутинг по ролям text/vision/table | ✅ |
| **SEP-хранилища** | LocalFS (NVMe) рабочий; S3/MinIO, WebDAV, GoogleDrive — классы-заготовки | 🔶 частично |

---

## Пайплаин обработки

```mermaid
flowchart TD
    A[PDF скан] --> B[PdfSourceAdapter<br/>блоки + bbox + стиль]
    B --> C[NormalizationAnalyzer]
    C --> D[ReadingOrderAnalyzer<br/>Reading Graph DAG]
    D --> E[DiagramDetectorAnalyzer]
    E --> F[HeadingAnalyzer<br/>дерево контейнеров]
    F --> G[TitlePageAnalyzer]
    G --> H[TableDetector / Caption]
    H --> PA[PageAgent<br/>vision: role + пересборка<br/>title/toc/table]
    PA --> I[BlockClassifier]
    I --> J[LLMRefinement<br/>ollama-агент]
    J --> K[EntityExtractor<br/>Knowledge Graph]
    K --> L{confidence < 0.85?}
    L -- да --> M[HITL / Агент стр.]
    L -- нет --> N[KRM + persist JSON]
    M --> N
    N --> O[Перевод ollama]
    O --> P[XeLaTeX сборка → PDF + .kap]
```

Пайплайн собирается в [`src/analyzers/pipeline.py`](src/analyzers/pipeline.py)
(`PipelineRunner` с проверкой прав анализаторов и rollback при сбое, RFC 0005).

---

## Архитектурные RFC (`docs/architecture/`)

| RFC | Тема |
|---|---|
| 0001 | Overview & Vision |
| 0002 | Knowledge Representation Model (KRM) |
| 0003 | Knowledge Graph |
| 0004 | Reading Graph |
| 0005 | Analyzer API & Permissions Matrix |
| 0006 | Skills & Recipes |
| 0007 | AI Knowledge Layer & Chunking |
| 0008 | Source Adapters |
| 0009 | Benchmark & Corpus |
| 0010 | Plugin API & Sandbox |
| 0011 | Provenance & Lineage |
| 0012 | Reproducible Builds (`kae.lock`) |
| 0013 | Artifact & Content-Addressed Store (`.kap`) |
| 0014 | Contract Testing |
| 0015 | Error Taxonomy |
| 0016 | Human-in-the-Loop |
| 0017 | Confidence Calibration |
| 0018 | Retrieval & Dataset Eval |
| 0019 | Job & Resource Manager |
| 0020 | Security & Trust |
| 0021 | Target Document Assembly & Translation |
| 0022 | GPU Runner Orchestration (Manager+Runner, on-demand GPU) |

Степень соответствия кода каждому RFC — в [`COMPLIANCE_AUDIT.md`](docs/architecture/COMPLIANCE_AUDIT.md).

---

## Структура проекта

```
BookAssembler/
├── Dockerfile               # backend (FastAPI) + frontend (Vite) + XeLaTeX (texlive)
├── docker-compose.yml       # kae-engine: порт 3000 (UI) / 8000 (API), volume /data
├── requirements.txt         # Python зависимости (fastapi, pymupdf, opencv, reportlab…)
├── server.ts                # Node gateway: раздаёт SPA + проксирует /api на FastAPI
│
├── src/
│   ├── adapters/            # PdfSourceAdapter + SEP-провайдеры (LocalFS, S3, WebDAV…)
│   ├── analyzers/           # пайплайн: normalization, reading_order, heading,
│   │                        #   title_page, table_detector, caption_analyzer,
│   │                        #   block_classifier, llm_refinement, entity_extractor,
│   │                        #   diagram_detector, pipeline (PipelineRunner)
│   ├── krm/                 # models.py — типы KRM (ContainerUnit, ParagraphBlock,
│   │                        #   TitlePageBlock, DiagramBlock, TableBlock…)
│   ├── graph/               # knowledge_graph.py, reading_graph.py
│   ├── assembler/           # translator.py, latex_builder.py, diagram_vectorizer.py
│   ├── ai_layer/            # semantic chunker + exporter (RAG)
│   ├── hitl/ jobs/ audit/   # HITL-менеджер, задачи (pyjobkit-мост), audit-лог
│   ├── api/
│   │   ├── app.py           # FastAPI: импорт, пайплайн, графы, перевод, сборка, агенты
│   │   └── client.ts        # типизированный REST/SSE клиент
│   ├── components/          # React UI (CleanWorkspace, DocumentDashboard, …)
│   └── App.tsx              # SPA
│
├── docs/architecture/       # RFC 0001–0022 + COMPLIANCE_AUDIT.md
└── colab/                   # GPU-агенты на Colab/Kaggle (см. ниже)
    ├── kae_gpu_agent.ipynb        # ollama (vision/coder) через cloudflared-туннель
    ├── kae_got_ocr.ipynb          # GOT-OCR2.0 (таблицы/формулы) как HTTP-сервис
    └── kae_multimodel_agent.ipynb # Qwen2.5-VL 2×T4 fp16 — table/formula/vision по /infer
```

---

## Запуск (Docker)

Backend, frontend и XeLaTeX собираются в один образ.

```bash
docker compose up -d --build
```

- UI: `http://<host>:3000`
- API: `http://<host>:8000/api/v1`
- Данные (импортированные PDF, KRM-JSON, сборки): volume `/data`

Импорт: в UI **«Импорт из SEP»** → выбери PDF из подключённого LocalFS-провайдера
(по умолчанию — каталог данных на диске) → пайплайн запустится, прогресс идёт по SSE.

> Сборка фронтенда выполняется **внутри Docker** (`npm install` + `vite build` в
> Dockerfile). Локально `npm install` не требуется.

---

## GPU-агенты (Colab / Kaggle)

Тяжёлые модели (vision-векторизация схем, OCR таблиц/формул) выносятся на бесплатный
GPU (Colab T4 или Kaggle T4×2) и подключаются как обычный агент в менеджере агентов
KAE. Секретный `Authorization: Bearer` защищает публичный туннель от чужих запросов
(планируется в RFC 0022).

- [`colab/kae_multimodel_agent.ipynb`](colab/kae_multimodel_agent.ipynb) — **основной**:
  Qwen2.5-VL-7B в fp16 с шардингом по 2×T4 (Kaggle), сервис `/health` + `/infer{task}`
  для задач `table` / `formula` / `vision`. Регистрируется в менеджере как
  `kind=multimodel` с ролями.
- [`colab/kae_got_ocr.ipynb`](colab/kae_got_ocr.ipynb) — **GOT-OCR2.0** отдельно
  (лучшее качество на таблицах, но несовместим по версии transformers с Qwen-VL).
- [`colab/kae_gpu_agent.ipynb`](colab/kae_gpu_agent.ipynb) — ollama с vision-моделью
  (`llava`), запасной вариант.

Локальные ollama-агенты (Raspberry Pi / Orange Pi) работают на CPU — годятся для
классификации/перевода; для vision-задач нужен GPU-агент.

**On-demand GPU (RFC 0022, в разработке):** двухуровневая архитектура — Manager
(CPU, всегда online) стартует Runner (GPU) по запросу и гасит по простою, чтобы
не сжигать Kaggle-квоту впустую.

---

## API (основное, `/api/v1`)

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/sep/providers` · `/sep/providers/{id}/browse` | список/навигация хранилищ |
| `POST` | `/sep/providers/{id}/import` | импорт PDF в пайплайн |
| `GET` | `/documents` · `/jobs/{id}/result` · `/jobs/{id}/progress` | документы, KRM, прогресс |
| `GET` | `/jobs/stream` | SSE-поток прогресса |
| `GET` | `/graph/{id}` | Knowledge Graph + Reading Graph |
| `POST` | `/jobs/{id}/refine` · `/jobs/{id}/refine-page/{page}` | агент: блок / вся страница |
| `POST` | `/jobs/{id}/translate/start` · `/jobs/{id}/assemble` | перевод / сборка книги |
| `GET` | `/jobs/{id}/diagram/{block}` | рендер региона схемы |
| `GET`/`POST`/`PUT`/`DELETE` | `/agents/config` | менеджер агентов |

---

## Лицензия

MIT.
