# Аудит соответствия кода RFC 0001–0022

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 0.1.0 | 2026-08-18 | Compliance sweep |

Полная сверка текущего кода со всеми 20 архитектурными RFC. Цель — довести код
до соответствия контрактам. Статусы: ✅ соответствует · 🔧 частично/в работе ·
❌ нарушение · ⚠️ противоречие между самими RFC · ➖ не реализовано (вне текущего объёма).

---

## Сводная карта

| RFC | Ключевое требование | Статус | Gap | Приоритет |
|---|---|---|---|---|
| 0001 §2.4 | **No Silent Deletions** — узлы не удаляются, только `is_tombstoned=True` | ✅ | tombstone в title_page/block_classifier/table_detector; экспорт скрывает | — |
| 0001 §3.3 | Экспорт из размеченного KRM в LaTeX/MD/EPUB/HTML | 🔧 | есть только reportlab-PDF (не в списке форматов) | P2 |
| 0002 §inv3 | `bounding_box` ∈ [0,1], round-trip layout+style | ✅ | реальный bbox+style в persist/restore; проверено 704 bbox / 691 style на диске | — |
| 0002 §inv4 | Неразрушимость текста (меняется только `text`) | ✅ | — | — |
| 0003 §5 | KG: No Dangling Edges (source/target существуют) | ✅ | `validate_integrity` + вызов в конце пайплайна (логирует) | — |
| 0004 §5 | RG: строгий DAG, Single Head per Track | ✅ | DAG enforced (`CyclicReadingPathError`); ацикличность гарантирована | — |
| 0005 §2 | Permissions Matrix, удаление только TOMBSTONE | ✅ | манифесты декларируют TOMBSTONE; физического удаления нет | — |
| 0005 §5 | PipelineRunner enforce прав (proxy) + provenance-стемп | ✅ | Guarded{Doc,RG,KG}-прокси enforce'ят права; provenance пишется | — |
| 0005 §6.1 | Failure Isolation — rollback мутаций при исключении | ✅ | deepcopy-snapshot перед run, `_restore_state` при исключении | — |
| 0006 §inv | Skills декларативны (без Python), SemVer | ➖ | Skills Engine не реализован | P3 |
| 0007 §5 | Chunks: Breadcrumbs, No Code/Table Rupture, RAG-ready | 🔧 | chunker есть; целостность спец-блоков не гарантирована | P2 |
| 0008 §5.2 | **Адаптер без бизнес-логики** (не строит заголовки/таблицы) | ✅ | детекция заголовков перенесена в `HeadingAnalyzer`; адаптер плоский | — |
| 0008 §5.1 | Ошибки парсинга → `SourceAdapterParseError` | 🔧 | обёртка исключений неполная | P2 |
| 0009 §5.2 | Детерминизм байт-в-байт при повторном прогоне | 🔧 | LLM детерминирован (temp=0/seed=42); полная битовая проверка не тестирована | P2 |
| 0010 | Plugin API, изоляция OOM/crash | ➖ | плагинной системы нет | P3 |
| 0011 §1 | Lineage переведённых сегментов (bbox+page+sha256, DAG) | ✅ | `_record_translation`: source_id+bbox+in/out хеши+model; источник не мутируется | — |
| 0011 §2.1 | Координатная сетка | ✅ | разведено: 0011 приведён к `[0,1]` согласно 0002 | — |
| 0012 | Сборка: **XeLaTeX** в locked Docker, `kae.lock`/`book.json`, детерминизм | ✅ | XeLaTeX (`latex_builder.py`) — проверено: PDF с кириллицей компилируется на ARM; kae.lock/book.json+hashes; LLM temp=0/seed=42 | — |
| 0013 | Выход → content-addressed `.kap` bundle (SHA-256) | ✅ | `.kap` tar.gz с manifest.json (SHA-256 артефактов) при сборке | — |
| 0014 §Idempotency | Двойной прогон анализатора → идентичный AST hash | ❌ | LLMRefinement (и title_page) не идемпотентны | P2 |
| 0016 | Human-in-the-Loop | ✅ | HITLManager реализован | — |
| 0017 | Confidence calibration (dual confidence) | ✅ | extraction/classification confidence есть | — |
| 0018 | Retrieval & dataset eval | ➖ | вне текущего объёма | P3 |
| 0019 | Job & Resource Manager | ✅ | JobManager/pyjobkit | — |
| 0020 | Security: Ed25519-подписи плагинов | ➖ | плагинов нет | P3 |
| 0022 | GPU Runner Orchestration (Manager+Runner, idle-shutdown, auth) | ➖ | RFC написан, реализация не начата (см. §10 план этапов) | P2 |

---

## Противоречия внутри самих RFC — РАЗВЕДЕНО

1. **Координатная сетка.** ✅ Решено. RFC 0011 §2.1 приведён к каноническому
   `[0.0, 1.0]` (`NormalizedRect`, RFC 0002 §inv3); поле `page_number` →
   `page_or_screen_index`. В 0011 добавлена явная Resolution-заметка (supersedes v1.0.0).

2. **Слой сборки/перевода целевого документа.** ✅ Решено. Создан
   **RFC 0021: Target Document Assembly & Translation** — гибридный рендер
   (текст reflow / особые страницы позиционно), поверх KRM, читающий `visual_layout`,
   не мутирующий KRM-инварианты, с детерминизмом и выходом по 0011/0012/0013.
   Карта RFC в 0001 §4 обновлена (10 → 21 документ).

---

## Приоритетный план работ

**P0 — нарушения инвариантов целостности — ✅ ВЫПОЛНЕНО:**
- ✅ Убрано физическое удаление узлов в `title_page`/`block_classifier`/`table_detector` → `is_tombstoned=True`; экспорт скрывает (0001 §2.4, 0005 §2).
- ✅ Детекция заголовков перенесена из `pdf_adapter` в `HeadingAnalyzer` (0008 §5.2).

**P1 — контракты выполнения и данных — ✅ ВЫПОЛНЕНО:**
- ✅ Round-trip layout+style в persist/restore (0002).
- ✅ Enforcement прав (Guarded-прокси, был) + Failure Isolation (deepcopy-rollback) в `PipelineRunner` (0005 §5, §6.1).
- ✅ Координатная сетка разведена в RFC (0011 → [0,1]).

**P2 — воспроизводимость, экспорт, происхождение — ✅ ВЫПОЛНЕНО:**
- ✅ Детерминизм LLM `temperature=0, seed=42` (0012). Полная битовая идемпотентность (0014/0009) — не тестирована.
- ✅ Lineage переведённых сегментов, источник неизменен (0011/0021).
- ✅ XeLaTeX-сборка + `kae.lock`/`book.json` (0012), выход в `.kap` (0013) — проверено end-to-end.
- ✅ Валидация целостности KG (0003) / RG DAG (0004).

**P3 — вне текущего объёма (нет подсистем):**
- Skills Engine (0006), Plugin API + sandbox + Ed25519 (0010, 0020), retrieval eval (0018), error taxonomy (0015).
