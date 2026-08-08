# RFC 0004: Reading Graph Specification

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Reading Graph (RG) — это специализированный ориентированный ациклический граф (DAG), определяющий порядки чтения и траектории обхода содержимого документа.

В сложных сверстанных источниках (двухколоночные газеты/журналы, технические руководства с боковыми выносками, книги со сносками и плавающими врезками) линейный порядок следования узлов в файле не совпадает с реальным порядком чтения человека.

Попытка зафиксировать единственный жесткий порядок чтения неизбежно ломает логику либо боковых заметок, либо основного текста. Reading Graph решает эту проблему за счет концепции мультитрекового обхода (Multi-track Reading Flow).

```
                  [ Header / Chapter Title ]
                              │
                              ▼
                   [ Layout Region: Main ]
                    ┌─────────┴─────────┐
                    ▼                   ▼
            [ Main Flow (Col 1) ]   [ Main Flow (Col 2) ]
                    │                   │
                    └─────────┬─────────┘
                              ▼
                   [ Layout Region: Sidebar ]
                              │
                              ▼
                     [ Sidebar Flow ]
```

## 2. Модель данных Графа Чтения
Reading Graph представляет собой ориентированный граф $G_{R} = (V_{R}, E_{R})$, где:
- $V_{R}$ — узлы KRM (преимущественно `StructuralUnit`, такие как `ParagraphBlock`, `HeadingBlock`, `TableBlock`).
- $E_{R}$ — направленные дуги переходного порядка чтения, снабженные атрибутом `Track`.

### 2.1. Треки чтения (Reading Tracks)
Граф чтения состоит из нескольких параллельных или ответвляющихся потоков:

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

class ReadingTrack(Enum):
    MAIN_FLOW = "main_flow"          # Основной нарративный поток
    SIDEBAR_FLOW = "sidebar_flow"    # Поток боковых заметок и выносок
    FOOTNOTE_FLOW = "footnote_flow"  # Поток сносок внизу страницы
    CAPTION_FLOW = "caption_flow"    # Поток описаний рисунков/таблиц
    CODE_EXPLANATION = "code_expl"   # Поток построчных комментариев к коду
```

### 2.2. Дуги графа чтения (Reading Edges)
Каждое ребро указывает, какой узел логически следует за текущим в рамках конкретного трека.

```python
@dataclass
class ReadingEdge:
    source_id: str
    target_id: str
    track: ReadingTrack = ReadingTrack.MAIN_FLOW
    confidence: float = 1.0
    provenance_analyzer: str = ""
```

## 3. Спецификация класса ReadingGraph
`ReadingGraph` предоставляет методы для построения траекторий чтения, объединения разорванных контекстов и получения строго упорядоченных последовательностей узлов для генерации Markdown/LaTeX или RAG-чанков.

```python
class ReadingGraph:
    def __init__(self):
        self._edges: List[ReadingEdge] = []
        self._adjacency_out: Dict[str, List[ReadingEdge]] = {}
        self._adjacency_in: Dict[str, List[ReadingEdge]] = {}

    def add_step(
        self, 
        source_id: str, 
        target_id: str, 
        track: ReadingTrack = ReadingTrack.MAIN_FLOW,
        confidence: float = 1.0,
        analyzer_name: str = ""
    ) -> None:
        edge = ReadingEdge(
            source_id=source_id,
            target_id=target_id,
            track=track,
            confidence=confidence,
            provenance_analyzer=analyzer_name
        )
        self._edges.append(edge)
        self._adjacency_out.setdefault(source_id, []).append(edge)
        self._adjacency_in.setdefault(target_id, []).append(edge)

    def get_sequence(self, root_id: str, track: ReadingTrack = ReadingTrack.MAIN_FLOW) -> List[str]:
        """
        Возвращает линейную последовательность ID узлов для заданного трека,
        начиная с root_id (обход DAG).
        """
        sequence = [root_id]
        current_id = root_id
        visited: Set[str] = {root_id}

        while True:
            outgoing = [
                e for e in self._adjacency_out.get(current_id, []) 
                if e.track == track and e.target_id not in visited
            ]
            if not outgoing:
                break
            # Выбираем дугу с наибольшей уверенностью
            best_edge = max(outgoing, key=lambda e: e.confidence)
            current_id = best_edge.target_id
            visited.add(current_id)
            sequence.append(current_id)

        return sequence
```

## 4. Алгоритмы объединения разорванных текстов (Cross-page Stitching)
Одной из главных задач `ReadingGraph` является правильное связывание абзацев, разорванных переносом на следующую страницу или разделенных плавающей фигурой.

```
Страница N                              Страница N+1
┌───────────────────────────────┐       ┌───────────────────────────────┐
│ ...процессор выполняет команду│       │которая сбрасывает шину в     │
│ [Block A]                     │       │исходное состояние. [Block B]  │
└───────────────────────────────┘       └───────────────────────────────┘
                │                                       ▲
                └────── ( MAIN_FLOW Reading Edge ) ─────┘
```

1. `LayoutAnalyzer` определяет, что `Block A` завершается без финальной точки или с дефисом переноса (`-`).
2. `ReadingGraph` формирует ребро `ReadingEdge(source_id="Block_A", target_id="Block_B", track=MAIN_FLOW)`.
3. При экспорте или линейной читке текст `Block A` и `Block B` склеивается без внедрения разрыва абзаца, а дефис переноса удаляется на этапе Normalization.

## 5. Инварианты Графа Чтения
1. **Отсутствие циклов (Acyclicity):** `ReadingGraph` обязано являться строгим DAG (Directed Acyclic Graph) в пределах каждого `ReadingTrack`. Зацикливание порядка чтения недопустимо.
2. **Единственность начального узла на трек (Single Head per Track):** Для каждого контейнера контента (`ContainerUnit`) у каждого трека чтения должен существовать ровно один корневой узел без входящих рёбер этого трека.
3. **Защита от изолированных блоков (No Isolation):** Каждая блочная сущность KRM, не находящаяся в состоянии `is_tombstoned = True`, должна входить хотя бы в один `ReadingTrack`.
