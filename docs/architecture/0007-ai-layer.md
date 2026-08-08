# RFC 0007: AI Knowledge Layer & Chunking

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает архитектуру и контракты AI Knowledge Layer — слоя, отвечающего за трансформацию обогащенной модели KRM, Графа Знаний (KG) и Графа Чтения (RG) в машиночитаемые артефакты, готовые для векторных баз данных (RAG), дообучения моделей (Fine-Tuning/SFT) и поиска.

Классический подход к нарезке текста под RAG (символьный/токеновый нахлест, например 1000 символов с overlap 200) разрушает смысловую целостность:
- Формулы, листинги кода и таблицы разрываются посередине.
- Теряется контекст контейнера (из какого раздела/подраздела взят фрагмент).
- Уничтожаются перекрестные ссылки и связи с иллюстрациями.

AI Knowledge Layer в KAE заменяет механический chunking на семантическую сборку единиц знаний (Semantic Unit Chunking) с внедрением контекстных хлебных крошек (Breadcrumbs), метаданных геометрии и прямых связей графа.

## 2. Архитектура Семантического Чанкинга (Semantic Chunking)
Чанком в KAE является не произвольный отрезок символов, а структурная или семантическая единица KRM (`KnowledgeUnit`), собранная с учетом траекторий `ReadingGraph`.

```
                    [ KnowledgeDocument ]
                              │
               [ Container: Chapter 4 / Section 4.2 ]
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   [ Chunk 1 ]          [ Chunk 2 ]          [ Chunk 3 ]
(InstructionSpec)     (CodeListingBlock)    (TableBlock)
```

### 2.1. Иерархические границы чанков (Chunk Boundaries)
- **Атомарные блоки (Non-splittable Units):** `TableBlock`, `CodeBlock`, `FormulaBlock`, `FigureBlock`, `InstructionSpec`, `DefinitionSpec`. Эти объекты категорически запрещено делить на части. Они формируют независимые чанки независимо от их размера.
- **Составные абзацы (Narrative Units):** Логически связанные группы `ParagraphBlock` объединяются в один чанк до тех пор, пока не превысят заданный лимит токенов (например, 512 или 1024 токена) или пока не встретится заголовок нового раздела.
- **Хлебные крошки (Contextual Breadcrumbs):** Каждый чанк автоматически предваряется полнотекстовым описанием его положения в иерархии документа.

## 3. Спецификация структуры AI Chunk (AIContextChunk)

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from uuid import uuid4

@dataclass
class ChunkBreadcrumbs:
    document_title: str
    container_path: List[str]  # e.g. ["Chapter 4. Hardware", "Section 4.2. DMA Controller"]
    page_numbers: List[int]

    def to_header_string(self) -> str:
        path_str = " > ".join(self.container_path)
        return f"[Context: {self.document_title} | {path_str} | Pages: {self.page_numbers}]"

@dataclass
class AIContextChunk:
    chunk_id: str = field(default_factory=lambda: str(uuid4()))
    source_krm_ids: List[str] = field(default_factory=list)  # Ссылки на исходные блоки KRM
    
    # Текстовое представление для векторного индексирования
    text_content: str = ""           # Чистый текст блока
    contextual_text: str = ""       # Breadcrumbs + text_content (для векторной эмбеддинг-модели)
    
    # Семантические метаданные
    chunk_type: str = "narrative"   # 'narrative', 'code', 'table', 'instruction', 'definition'
    language_or_arch: Optional[str] = None  # e.g., 'python', 'x86_asm'
    
    # Связи с другими чанками и объектами графа
    parent_container_id: str = ""
    previous_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    related_figure_ids: List[str] = field(default_factory=list)
    related_table_ids: List[str] = field(default_factory=list)
    mentioned_entities: List[str] = field(default_factory=list)
    
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## 4. Форматы экспорта AI Knowledge Layer
По завершении работы анализаторов и сборщика графов ядро KAE генерирует комплект файлов машинного слоя в директории `export/ai/`.

### 4.1. Манифест чанков (chunks_manifest.json)
Представляет собой готовую базу объектов для загрузки в векторные хранилища (Chroma, Qdrant, Milvus, Pinecone).

```json
{
  "schema_version": "1.0.0",
  "document_id": "doc_8f9a01",
  "total_chunks": 142,
  "chunks": [
    {
      "chunk_id": "chk_1024",
      "chunk_type": "instruction",
      "contextual_text": "[Context: Intel 8086 Manual > Chapter 2. Instruction Set > Section 2.1. Data Transfer] \nInstruction: MOV destination, source\nFlags affected: None. Description: Copies a byte or word from the source operand to the destination operand.",
      "raw_text": "Instruction: MOV destination, source\nFlags affected: None...",
      "breadcrumbs": {
        "document_title": "Intel 8086 Manual",
        "container_path": ["Chapter 2. Instruction Set", "Section 2.1. Data Transfer"],
        "page_numbers": [34, 35]
      },
      "relationships": {
        "previous_chunk_id": "chk_1023",
        "next_chunk_id": "chk_1025",
        "related_tables": ["tbl_04"],
        "mentioned_entities": ["AX", "BX", "READY_SIGNAL"]
      }
    }
  ]
}
```

### 4.2. Граф знаний для RAG (knowledge_graph_rag.json)
Формат представления графа сущностей и связей для гибридного RAG (GraphRAG / LightRAG).

```json
{
  "nodes": [
    {
      "id": "ent_ready",
      "label": "READY Signal",
      "type": "hardware_component"
    },
    {
      "id": "chk_1024",
      "label": "MOV Instruction Chunk",
      "type": "chunk"
    }
  ],
  "edges": [
    {
      "source": "chk_1024",
      "target": "ent_ready",
      "relation": "MENTIONS_ENTITY",
      "weight": 0.95
    }
  ]
}
```

## 5. Инварианты AI Knowledge Layer
1. **Сохранение абсолютного контекста (Context Preservation):** Поле `contextual_text` каждого чанка в обязательном порядке включает Breadcrumbs. Чанк не должен существовать без указания его места в общей структуре знания.
2. **Идеология целостности спец-блоков (No Code/Table Rupture):** Ни при каких условиях `CodeBlock` или `TableBlock` не режутся на части из-за лимита длины. В случае превышения лимита модели генерируется специальный составной чанк с указанием связи продолжения (`continuation_of`).
3. **Прямая совместимость с RAG (RAG Ingestion Ready):** Сформированный манифест должен быть полностью валидным JSON, готовым к немедленной индексации без дополнительного парсинга со стороны вызывающего приложения.
