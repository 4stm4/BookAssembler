# RFC 0008: Source Adapters Architecture

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает архитектуру, интерфейсы и контракты слоя Source Adapters (Входные адаптеры).

Одна из главных архитектурных проблем традиционных систем анализа документов — просачивание специфики входного формата (байты и структуры PDF, DOM-дерево HTML, XML-теги OpenXML DOCX) в ядро обработки. Это делает систему узкоспециализированной и мешает поддержке новых форматов.

В Knowledge Assembly Engine (KAE) слой Source Adapters выступает единственным шлюзом ввода.

**Главное правило слоя:**
Ни один модуль системы (за исключением конкретного класса `SourceAdapter`) не знает о природе исходного файла. Все последующие этапы (Normalization, Analyzers, Skills, AI Layer) работают исключительно с необработанной моделью знания — Unprocessed KRM.

```
 [ PDF / Scan ]      ──> [ PDFAdapter ]        ┐
 [ DOCX / ODT ]      ──> [ DocxAdapter ]       │
 [ HTML / Wiki ]     ──> [ WebAdapter ]        ├──> [ Unprocessed KRM ] ──> [ Pipeline Engine ]
 [ Git Repo / Code ] ──> [ CodeRepoAdapter ]   │
 [ Jupyter / RST ]   ──> [ NotebookAdapter ]   ┘
```

## 2. Базовый контракт SourceAdapter
Каждый адаптер должен наследоваться от абстрактного класса `BaseSourceAdapter` и реализовывать методы парсинга источников в базовый `KnowledgeDocument`.

```python
from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_name: str
    supported_extensions: List[str]  # e.g. ["pdf"], ["docx"], ["ipynb"]
    supported_mimeTypes: List[str]   # e.g. ["application/pdf"]
    provides_visual_layout: bool     # Имеются ли оригинальные координаты BBox и шрифты
    provides_reading_order: bool     # Предоставляет ли источник исходную последовательность

class BaseSourceAdapter(ABC):
    def __init__(self, capabilities: AdapterCapabilities):
        self._capabilities = capabilities

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    @abstractmethod
    def parse(
        self, 
        stream: BinaryIO, 
        source_uri: str, 
        options: Optional[Dict[str, Any]] = None
    ) -> "KnowledgeDocument":
        """
        Принимает бинарный поток источника и преобразует его в сырой Unprocessed KRM.
        
        Гарантии метода:
        1. Создание исходной иерархии (KnowledgeDocument -> ContainerUnit -> StructuralUnit).
        2. Присвоение каждому созданному узлу уникального UUIDv4.
        3. Заполнение ProvenanceInfo с указанием базового адаптера.
        """
        pass
```

## 3. Специфика отдельных типов адаптеров

### 3.1. PDFAdapter
- **Входные данные:** Физический PDF-файл (цифровой или скан).
- **Библиотеки рендеринга:** PyMuPDF (fitz), PDFMiner или специализированные C-bindings.
- **Особенности:**
  - Сохраняет точный `VisualLayout` (абсолютные координаты bounding box, имена и размеры шрифтов).
  - Извлекает растровые и векторные изображения как самостоятельные `FigureBlock`.
  - Если текстовый слой отсутствует или поврежден, помечает узлы флагом `needs_ocr = True` для последующей обработки в `OCRAnalyzer`.

### 3.2. DocxAdapter
- **Входные данные:** Документы Microsoft Word (.docx).
- **Особенности:**
  - Читает встроенные стили OpenXML (Heading 1..6, Title, Caption, Code).
  - Таблицы извлекаются с сохранением объединения ячеек (`row_span`, `col_span`).
  - `VisualLayout` строится условно (координаты BBox отсутствуют, но сохраняется последовательный порядок блоков).

### 3.3. HTML / Wiki / Markdown Adapter
- **Входные данные:** Веб-страницы, статьи Confluence/MediaWiki, файлы Markdown.
- **Особенности:**
  - Строит иерархию контейнеров на основе заголовков `<h1>`–`<h6>` или синтаксиса `#`–`######`.
  - Извлекает метаданные (OpenGraph, HTML meta-tags, YAML Frontmatter).
  - Кодовые блоки (`<pre><code>` или triple backticks) сразу оборачиваются в `CodeBlock`.

### 3.4. CodeRepo / Notebook Adapter
- **Входные данные:** Jupyter Notebooks (.ipynb) или файловое дерево репозитория.
- **Особенности:**
  - Ячейки Markdown становятся `ParagraphBlock`.
  - Ячейки Code становятся `CodeBlock` с привязкой языка исполнения.
  - Выводы ячеек (Cell Outputs: графики, таблицы, консольный вывод) связываются с соответствующим `CodeBlock` через Граф Знаний (`CONCRETIZES`).

## 4. Каноническое состояние Unprocessed KRM
После работы любого адаптера сформированный `KnowledgeDocument` переходит в состояние Unprocessed KRM и обязан соответствовать каноническому контракту:
1. **Единственный корень:** Существует ровно один узел `KnowledgeDocument`, содержащий заголовок, `source_uri` и системные метаданные.
2. **Отсутствие зацепления за сторонние типы:** Внутри KRM отсутствуют ссылки на типы данных сторонних библиотек (`fitz.Page`, `docx.Document`, `bs4.BeautifulSoup`). Все сущности приведены к типам KRM.
3. **Безусловная UUID-идентификация:** У каждого узла заполнены `id` (UUIDv4) и объект `provenance_info`.

## 5. Инварианты слоя адаптеров
1. **Строгая изоляция исключений (Adapter Exception Wrapping):** Любая ошибка парсинга входного формата (поврежденный zip-архив docx, битый поток PDF, некорректный JSON notebook) перехватывается адаптером и выбрасывается как унифицированное исключение `SourceAdapterParseError`.
2. **Запрет на бизнес-логику и семантический анализ:** Адаптер не имеет права выполнять сложный анализ (распознавать таблицы, искать перекрестные ссылки, определять операнды ассемблера). Его задача — чистая конвертация входной структуры в KRM.
3. **Потоковая обработка (Stream Safety):** Адаптеры обязаны работать с абстрактными файловыми потоками (`BinaryIO`), а не завязываться исключительно на имена файлов на диске.
