# RFC 0005: Analyzer API & Permissions Matrix

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает контракты, интерфейсы и систему прав доступа (Permissions Matrix) для компонентов типа Analyzer.

Анализатор (Analyzer) в Knowledge Assembly Engine (KAE) — это изолированный модуль обработки, преобразующий и обогащающий состояние документов (KRM), графа чтения (Reading Graph) и графа знаний (Knowledge Graph).

Главная цель этого RFC — пресечь бесконтрольную модификацию данных. Ни один анализатор не должен иметь неограниченных прав на весь документ. Каждое действие строго регламентируется и декларируется через систему разрешений (Capabilities & Permissions).

## 2. Разрешения (Analyzer Permissions)
Разрешения делятся на три категории в зависимости от целевого объекта: KRM, Reading Graph (RG) и Knowledge Graph (KG).

```python
from enum import Enum, auto

class KRMPermission(Enum):
    READ = auto()               # Чтение структуры и свойств KRM-узлов
    MUTATE_ATTRIBUTES = auto()  # Изменение текстового содержимого, стилей и метаданных
    TRANSFORM_NODE = auto()     # Замена класса узла (напр., ParagraphBlock -> HeadingBlock)
    INSERT = auto()             # Создание и вставка новых узлов в иерархию
    TOMBSTONE = auto()          # Пометка узла как удаленного (is_tombstoned = True)

class RGPermission(Enum):
    READ = auto()               # Чтение траекторий чтения
    MUTATE_EDGES = auto()       # Добавление/изменение/удаление дуг порядка чтения

class KGPermission(Enum):
    READ = auto()               # Чтение сущностей и связей
    MUTATE_ENTITIES = auto()    # Добавление и изменение внешних сущностей
    MUTATE_EDGES = auto()       # Добавление и изменение семантических связей
```

*Важно:* Ни одно разрешение не даёт права физически вычищать объект из памяти. Удаление заменяется установкой флага `is_tombstoned = True`.

## 3. Базовый контракт BaseAnalyzer
Каждый анализатор должен наследоваться от абстрактного класса `BaseAnalyzer` и задекларировать своё имя, версионность, зависимости и матрицу прав.

```python
from abc import ABC, abstractmethod
from typing import Set, Dict, List, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class AnalyzerManifest:
    name: str
    version: str
    description: str
    krm_permissions: Set[KRMPermission]
    rg_permissions: Set[RGPermission]
    kg_permissions: Set[KGPermission]
    depends_on: List[str]  # Имена анализаторов, которые должны выполниться ДО текущего

class BaseAnalyzer(ABC):
    def __init__(self, manifest: AnalyzerManifest):
        self._manifest = manifest

    @property
    def manifest(self) -> AnalyzerManifest:
        return self._manifest

    @abstractmethod
    def run(
        self, 
        doc: "KnowledgeDocument", 
        rg: "ReadingGraph", 
        kg: "KnowledgeGraph",
        context: Optional[Dict[str, any]] = None
    ) -> None:
        """
        Основной метод выполнения анализатора.
        Выполняет мутации в соответствии со своими задекларированными разрешениями.
        """
        pass
```

## 4. Матрица разрешений для ключевых анализаторов (Permissions Matrix)

| Анализатор | KRM Разрешения | RG Разрешения | KG Разрешения | Назначение |
|---|---|---|---|---|
| `NormalizationAnalyzer` | READ, MUTATE_ATTRIBUTES | READ | None | Очистка Unicode, раскрытие лигатур, склейка слов. |
| `LayoutAnalyzer` | READ, INSERT | READ, MUTATE_EDGES | None | Выделение регионов верстки и построение базового графа чтения. |
| `HeadingAnalyzer` | READ, TRANSFORM_NODE | READ | None | Классификация заголовков (H1-H6) и построение дерева контейнеров. |
| `CaptionAnalyzer` | READ, TRANSFORM_NODE | READ | READ, MUTATE_EDGES | Связывание плавающих блоков с их описаниями (CAPTION_FOR). |
| `TableAnalyzer` | READ, TRANSFORM_NODE, INSERT | READ | READ, MUTATE_EDGES | Распознавание структуры таблиц (ячейки, строки, столбцы). |
| `CodeSyntaxAnalyzer` | READ, MUTATE_ATTRIBUTES | READ | READ, MUTATE_ENTITIES, MUTATE_EDGES | Парсинг листингов кода, определение языка, выявление операндов. |
| `CrossLinkAnalyzer` | READ | READ | READ, MUTATE_EDGES | Поиск внутритекстовых ссылок («см. рис. 3») и построение рёбер REFERENCES. |

## 5. Исполнительный конвейер (Pipeline Runner) и защита прав
Выполнение анализаторов происходит под контролем класса `PipelineRunner`. Он проверяет соблюдение объявленных в манифесте прав до и после вызова `run()`.

```python
class SecurityViolationError(Exception):
    """Исключение при попытке анализатора совершить заблокированное действие."""
    pass

class PipelineRunner:
    def __init__(self, analyzers: List[BaseAnalyzer]):
        self._analyzers = analyzers
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        executed: Set[str] = set()
        for analyzer in self._analyzers:
            for dep in analyzer.manifest.depends_on:
                if dep not in executed:
                    raise ValueError(
                        f"Анализатор '{analyzer.manifest.name}' требует выполнения '{dep}', "
                        f"но он не был запущен ранее."
                    )
            executed.add(analyzer.manifest.name)

    def execute(
        self, 
        doc: "KnowledgeDocument", 
        rg: "ReadingGraph", 
        kg: "KnowledgeGraph"
    ) -> None:
        for analyzer in self._analyzers:
            # Здесь ядро создает прокси-обертки над doc, rg, kg, 
            # блокирующие операции, выходящие за границы manifest.
            analyzer.run(doc, rg, kg)
            # Добавление имени анализатора в ProvenanceInfo модифицированных узлов
```

## 6. Инварианты выполнения анализаторов
1. **Изоляция сбоев (Failure Isolation):** Если анализатор выбрасывает исключение во время выполнения `run()`, транзакция мутации откатывается, а документ возвращается в состояние до запуска текущего анализатора.
2. **Запрет циклов вызова:** Конвейер анализаторов strictly sequential (строго последовательный) и детерминированный. Запрещены прямые вызовы одного анализатора из другого.
3. **Декларация зависимостей:** Любая цепочка анализаторов валидируется на этапе старта конвейера. Если зависимость не удовлетворена, выполнение не начинается.
