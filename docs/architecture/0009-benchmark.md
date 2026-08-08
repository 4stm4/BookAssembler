# RFC 0009: Benchmark & Corpus Specification

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает систему тестирования, метрики качества и состав контрольного корпуса документов (Corpus & Benchmark Suite) в Knowledge Assembly Engine (KAE).

В крупных открытых и коммерческих проектах обработки документов ключевая проблема развития — отсутствие объективной оценки изменений (Regression Control). Внесение «улучшений» под верстку книг одного издательства (например, Intel) часто неявно ломает извлечение таблиц или порядка чтения в книгах других издательств (например, Addison-Wesley или советских сканах).

Benchmark Suite решает эту проблему за счет введения:
- Фиксированного эталонного корпуса документов (Golden Corpus).
- Машиночитаемых эталонных разрядок (Golden Truth Dataset).
- Набора точных квантитативных метрик (TEDS, WER/CER, Link Recall, Layout IoU).

Ни одно изменение в анализаторах, алгоритмах или навыках (Skills) не может быть принято в основную ветку без прохождения Бенчмарка и подтверждения отсутствия регрессии.

## 2. Структура Тестового Корпуса (Golden Corpus)
Корпус размещается в изолированном каталоге `tests/benchmark/corpus/` и содержит репрезентативные образцы верстки из разных доменов и эпох.

```
tests/benchmark/
├── corpus/
│   ├── intel_8086_manual/
│   │   ├── input.pdf
│   │   └── expected/
│   │       ├── krm_tree.json
│   │       ├── reading_graph.json
│   │       ├── knowledge_graph.json
│   │       └── chunks_manifest.json
│   ├── addison_wesley_cpp/
│   │   ├── input.pdf
│   │   └── expected/ ...
│   ├── soviet_radio_1985_scanned/
│   │   ├── input.pdf
│   │   └── expected/ ...
│   ├── ieee_two_column_paper/
│   │   ├── input.pdf
│   │   └── expected/ ...
│   └── docx_specification/
│       ├── input.docx
│       └── expected/ ...
├── metrics/
│   ├── teds.py
│   ├── text_accuracy.py
│   └── graph_recall.py
└── runner.py
```

### 2.1. Категории документов в Корпусе
- **Hardware Manuals (Intel, Motorola, Zilog):** Сложная структура, многоколоночные листинги ассемблера, таблицы опкодов, временные диаграммы.
- **Academic Papers (IEEE, ACM):** Плотная двухколоночная верстка, математические формулы, плавающие рисунки с подписями, списки литературы.
- **Technical Books (Addison-Wesley, O'Reilly, MS Press):** Боковые заметки (Sidebars), многоуровневые заголовки, врезки с предупреждениями (Notes/Warnings).
- **Historical & Soviet Scans (1970–1990):** Сканы низкого качества, артефакты печати, перекосы страниц (Skew), смешанный текст и графики.
- **Modern Digital Sources (DOCX, Jupyter Notebooks, HTML):** Чистая структура без координатной сетки, встроенный код и интерактивные графики.

## 3. Метрики Качества (Quantitative Metrics)
Оценка работы KAE происходит по четырем ключевым векторам:

```
┌─────────────────────────────────────────────────────────┐
│                    KAE Benchmark Metrics                │
├─────────────────┬───────────────────┬───────────────────┤
│  Text & Syntax  │  Structure & Layout│  Graph & Semantic │
│  - WER / CER    │  - TEDS (Tables)  │  - Link Precision │
│  - Code Exact   │  - Layout IoU     │  - Link Recall    │
└─────────────────┴───────────────────┴───────────────────┘
```

### 3.1. Метрика структуры таблиц: TEDS (Tree Edit Distance for Structure)
Используется для оценки точности извлечения таблиц (`TableBlock`). Метрика измеряет редакционное расстояние между деревьями HTML/KRM эталонной и извлеченной таблицы.

$$\text{TEDS}(T_1, T_2) = 1 - \frac{\text{EditDistance}(T_1, T_2)}{\max(\vert{}T_1\vert{}, \vert{}T_2\vert{})}$$

*Целевое значение:* $\text{TEDS} \ge 0.95$.

### 3.2. Метрика точности текста: WER (Word Error Rate) и CER (Character Error Rate)
Оценивает точность распознавания текста (особенно актуально после слоев Normalization и OCR).

$$\text{WER} = \frac{S + D + I}{N}$$

Где:
- $S$ — количество замен слов (Substitutions).
- $D$ — количество удалений слов (Deletions).
- $I$ — количество вставок лишних слов (Insertions).
- $N$ — общее количество слов в эталоне.

*Целевое значение:* $\text{WER} \le 0.02$ для цифровых PDF, $\text{WER} \le 0.08$ для сканов.

### 3.3. Метрика связей и перекрестных ссылок: Link Precision & Recall
Оценивает качество построения KnowledgeGraph (ссылки на рисунки, таблицы, определения сущностей).

$$\text{Precision} = \frac{\vert{}E_{\text{correct}}\vert{}}{\vert{}E_{\text{extracted}}\vert{}}, \quad \text{Recall} = \frac{\vert{}E_{\text{correct}}\vert{}}{\vert{}E_{\text{expected}}\vert{}}$$

$$\text{Link F1} = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$

*Целевое значение:* $\text{Link F1} \ge 0.90$.

## 4. Запуск и Автоматизация (Benchmark Runner API)
Исполнитель бенчмарков представляет собой CLI-утилиту и набор pytest-плагинов, интегрируемых в CI/CD пайплайн.

```python
from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class BenchmarkReport:
    document_name: str
    teds_score: float
    wer_score: float
    link_f1_score: float
    passed: bool
    details: Dict[str, Any]

class BenchmarkRunner:
    def __init__(self, corpus_path: str):
        self._corpus_path = corpus_path

    def run_all(self) -> List[BenchmarkReport]:
        """
        Прогоняет весь корпус через текущую конфигурацию KAE и
        сравнивает результаты с Golden Truth.
        """
        reports = []
        # Логика прогона
        return reports
```

Команда запуска тестового прогона:
```bash
# Запуск полного бенчмарка с генерацией HTML-отчета
python -m tests.benchmark.runner --corpus-dir tests/benchmark/corpus --report-out build/benchmark_report.html

# Запуск проверки на регрессию (падение, если метрики ухудшились более чем на 0.5%)
python -m tests.benchmark.runner --strict-regression-check
```

## 5. Инварианты Бенчмарка
1. **Запрет на ручные правки Golden Dataset без RFC:** Изменение эталонных данных в `expected/` запрещено без соответствующего Pull Request с объяснением причин и пересмотра маркировки.
2. **Детерминированность генерации:** Прогон одного и того же файла корпуса через KAE должен давать 100% идентичный результат байт-в-байт в отчете KRM/Graph.
3. **Блокирующий CI/CD:** Падение метрики Link F1 или TEDS ниже установленного порога автоматически блокирует слияние (Merge) ветки кода.
