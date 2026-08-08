# RFC 0003: Knowledge Graph Specification

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Knowledge Graph (KG) в рамках Knowledge Assembly Engine (KAE) — это ориентированный атрибутированный граф связей, который существует параллельно с деревом документов (KRM) и графом чтения (Reading Graph).

Если KRM описывает иерархию контейнеров контента («раздел содержит параграф»), то Knowledge Graph описывает смысловые, логические и навигационные отношения между объектами («параграф ссылается на Рисунок 5», «Инструкция MOV использует Регистр AX», «Таблица 3 конкретизирует Алгоритм 2»).

```
   [ KRM Node: Structural ]              [ KRM Node: Structural ]
 (ParagraphBlock: "See Fig. 2")        (FigureBlock: "Bus Timing")
               │                                   │
               └────────── ( Edge: REFERENCES ) ───┘
```

## 2. Модель данных Графа Знаний
Граф знаний формально задаётся как $G = (V, E)$, где:
- $V$ — множество вершин (Entities / Knowledge Nodes).
- $E$ — множество направленных рёбер (Semantic Relations).

### 2.1. Вершины (Nodes)
Вершиной графа знаний может выступать:
1. **Любой узел KRM (`BaseKRMNode`):** по его уникальному `id` (например, `ParagraphBlock`, `TableBlock`, `FigureBlock`, `InstructionSpec`).
2. **Внешняя сущность (`Extracted Entity`):** предметная сущность, извлечённая из текста (например, термин, модель микросхемы, имя регистра, статус-флаг, API-метод).

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4

class EntityType(Enum):
    HARDWARE_COMPONENT = "hardware_component"  # e.g., 'Intel 8086', 'DMA Controller'
    REGISTER = "register"                      # e.g., 'AX', 'CR0'
    INSTRUCTION = "instruction"                # e.g., 'MOV', 'NOP'
    FLAG = "flag"                              # e.g., 'ZERO_FLAG'
    CONCEPT_TERM = "concept_term"              # e.g., 'Interrupt Vector'
    SOFTWARE_API = "software_api"              # e.g., 'CreateFileW'
    BIBLIOGRAPHY_CITE = "bibliography_cite"    # e.g., '[Knuth88]'

@dataclass
class KGEntityNode:
    """Узел сущности, не являющийся блоком документа."""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    entity_type: EntityType = EntityType.CONCEPT_TERM
    canonical_name: Optional[str] = None  # Алиас для нормализации
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 2.2. Направленные рёбра и отношения (Edges / Relations)
Каждое ребро связывает вершину-источник (`source_id`) с вершиной-целью (`target_id`) и наделяется семантическим типом, весом уверенности и метаданными.

```python
class RelationType(Enum):
    # Навигационные и ссылочные
    REFERENCES = "references"             # Текст ссылается на рисунок/таблицу/главу
    CAPTION_FOR = "caption_for"           # Текст является подписью к рисунку/таблицу
    FOOTNOTE_FOR = "footnote_for"         # Сноска объясняет фрагмент текста
    CONTINUATION_OF = "continuation_of"   # Элемент продолжен на следующей странице/блоке

    # Семантические и смысловые
    DEFINES_ENTITY = "defines_entity"     # Блок содержит определение сущности
    MENTIONS_ENTITY = "mentions_entity"   # Блок упоминает сущность
    CONCRETIZES = "concretizes"           # Таблица/код конкретизирует тезис
    EXEMPLIFIES = "exemplifies"           # Листинг кода является примером к описанию

    # Доменные (для техники и микроэлектроники)
    USES_REGISTER = "uses_register"       # Инструкция/код использует регистр
    AFFECTS_FLAG = "affects_flag"         # Опкод меняет флаг
    PART_OF_ARCHITECTURE = "part_of_arch" # Сущность входит в архитектуру

@dataclass
class KGEdge:
    source_id: str
    target_id: str
    relation_type: RelationType
    confidence: float = 1.0
    provenance_analyzer: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 3. Спецификация класса KnowledgeGraph
`KnowledgeGraph` изолирован от KRM и предоставляет атомарный API для управления связями без нарушения структуры документа.

```python
from typing import Set

class KnowledgeGraph:
    def __init__(self):
        self._entity_nodes: Dict[str, KGEntityNode] = {}
        self._edges: List[KGEdge] = []
        self._adjacency_out: Dict[str, List[KGEdge]] = {}
        self._adjacency_in: Dict[str, List[KGEdge]] = {}

    def add_entity(self, entity: KGEntityNode) -> None:
        self._entity_nodes[entity.id] = entity

    def add_edge(
        self, 
        source_id: str, 
        target_id: str, 
        relation_type: RelationType, 
        confidence: float = 1.0, 
        analyzer_name: str = ""
    ) -> None:
        edge = KGEdge(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            confidence=confidence,
            provenance_analyzer=analyzer_name
        )
        self._edges.append(edge)
        self._adjacency_out.setdefault(source_id, []).append(edge)
        self._adjacency_in.setdefault(target_id, []).append(edge)

    def get_outgoing_edges(self, node_id: str, relation_type: Optional[RelationType] = None) -> List[KGEdge]:
        edges = self._adjacency_out.get(node_id, [])
        if relation_type is None:
            return edges
        return [e for e in edges if e.relation_type == relation_type]

    def get_incoming_edges(self, node_id: str, relation_type: Optional[RelationType] = None) -> List[KGEdge]:
        edges = self._adjacency_in.get(node_id, [])
        if relation_type is None:
            return edges
        return [e for e in edges if e.relation_type == relation_type]
```

## 4. Сериализация и экспорт Графа Знаний
Knowledge Graph умеет экспортироваться в стандартизированные форматы без привлечения внешних библиотек для непосредственной передачи в векторные/графовые БД (Neo4j, Memgraph, FalkorDB) и RAG-пайплайны.

### Формат экспорта KAE-KG (JSON Schema)
```json
{
  "graph_version": "1.0.0",
  "entities": [
    {
      "id": "ent_9f8a12",
      "name": "READY Signal",
      "entity_type": "hardware_component",
      "canonical_name": "READY"
    }
  ],
  "edges": [
    {
      "source_id": "block_3a4b",
      "target_id": "fig_12",
      "relation_type": "references",
      "confidence": 0.98,
      "provenance_analyzer": "CrossLinkAnalyzer"
    },
    {
      "source_id": "block_3a4b",
      "target_id": "ent_9f8a12",
      "relation_type": "mentions_entity",
      "confidence": 0.95,
      "provenance_analyzer": "EntityExtractorSkill"
    }
  ]
}
```

## 5. Инварианты Графа Знаний
1. **Защита от висячих рёбер (No Dangling Edges):** Любой `source_id` и `target_id` должен соответствовать либо существующему узлу в KRM (`KnowledgeDocument`), либо зарегистрированной сущности `KGEntityNode`.
2. **Идеология мультиграфа:** Между двумя узлами $A$ и $B$ может существовать несколько рёбер разных типов (например, `ParagraphBlock` одновременно `REFERENCES` и `CONCRETIZES` объект `TableBlock`).
3. **Идемпотентность добавления:** Повторная запись одного и того же ребра (`source_id`, `target_id`, `relation_type`) от того же анализатора обновляет `confidence` и метаданные, но не плодит дубликаты.
