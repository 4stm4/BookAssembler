# RFC 0010: Plugin API & Sandbox Execution

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает архитектуру, интерфейсы и механизм изоляции (Sandbox Execution) внешних расширений (плагинов).

По мере развития Knowledge Assembly Engine (KAE) возникает необходимость подключать пользовательские адаптеры (`SourceAdapter`), анализаторы (`BaseAnalyzer`) и экспортные модули без изменения основного ядра системы.

Однако выполнение стороннего кода прямо в пространстве процесса ядра несёт фундаментальные риски:
- **Утечка прав и случайное повреждение данных:** Плагин без ограничений может изменить чужие узлы KRM или зациклить конвейер.
- **Неконтролируемое потребление ресурсов:** Падение по Out Of Memory (OOM) или бесконечный цикл в стороннем скрипте обрушивает весь процесс KAE.
- **Проблемы с безопасностью:** Чтение приватных ключей API, исполнение сторонних C-расширений, несанкционированный сетевой доступ.

RFC 0010 решает эти задачи через введение Plugin Management System с декларированием точек расширения (Extension Points) и возможностью выполнения внешних модулей в изолированном окружении (Sandbox Process / Container).

## 2. Точки расширения (Extension Points)
Плагин может внедрять свою логику только в строго определённых точках интеграции:

```
[ KAE Core ]
   ├── Extension Point 1: SourceAdapters  (e.g., EPUBAdapter, DjVuAdapter)
   ├── Extension Point 2: CustomAnalyzers (e.g., DomainChemFormulasAnalyzer)
   ├── Extension Point 3: Skills          (e.g., skill.custom.my_company_format)
   └── Extension Point 4: Exporters        (e.g., CustomNeo4jExporter)
```

## 3. Спецификация Манифеста Плагина (plugin.yaml)
Каждый плагин представляет собой отдельный каталог или архив, содержащий обязательный файловый манифест `plugin.yaml`.

```yaml
id: "plugin.org.chem_extractor"
name: "Chemistry Formula & Structure Extractor"
version: "1.2.0"
kae_core_version: ">=2.0.0"
author: "ChemAI Lab <dev@chemai.org>"
license: "MIT"

permissions:
  krm_permissions: ["READ", "INSERT"]
  rg_permissions: ["READ"]
  kg_permissions: ["READ", "MUTATE_ENTITIES", "MUTATE_EDGES"]
  allow_network: false
  max_memory_mb: 1024
  timeout_seconds: 300

entry_points:
  analyzers:
    - class: "src.chem_analyzer.ChemicalFormulaAnalyzer"
      target_recipe: "recipe.chemistry_papers"
```

## 4. Архитектура Песочницы (Sandbox Execution Framework)
Плагины выполняются в одном из двух режимов в зависимости от уровня доверия (Trust Level):

```
                       ┌────────────────────────────────────────┐
                       │           KAE Core Process             │
                       └───────────────────┬────────────────────┘
                                           │
                  ┌────────────────────────┴────────────────────────┐
                  ▼                                                 ▼
        [ In-Process Execution ]                           [ Out-of-Process Sandbox ]
      (Доверенные встроенные)                         (Внешние плагины сторонних разработчиков)
                  │                                                 │
        (Прямые вызовы Python)                             (IPC / gRPC / Process Isolation)
```

### 4.1. Trusted In-Process Execution (Доверенное выполнение)
- Применяется для официальных ядра-плагинов KAE.
- Выполняется в основном процессе Python.
- Ограничения прав (KRM/RG/KG Permissions Matrix) контролируются через декораторы и прокси-обёртки ядра.

### 4.2. Isolated Out-of-Process Sandbox (Изолированное выполнение)
- Применяется для всех плагинов сторонних разработчиков.
- Запускается в отдельном дочернем процессе Python (`multiprocessing` / `subprocess`) или в лёгком контейнере (Docker/Wasm).
- Обмен данными между ядром и плагином происходит через строго бинарный протокол RPC (gRPC / Shared Memory / JSON-IPC).

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class PluginSandboxRunner(ABC):
    """Интерфейс изоляции выполнения плагинов."""
    
    @abstractmethod
    def run_analyzer_sandboxed(
        self, 
        plugin_id: str, 
        analyzer_class: str, 
        doc_state: Dict[str, Any], 
        timeout_sec: int
    ) -> Dict[str, Any]:
        """
        1. Сериализует разрешенный срезу состояние KRM/Graph.
        2. Передает данные в изолированный процесс плагина.
        3. Принимает дифференциальный патч изменений (Diff/Delta).
        4. Валидирует патч на соответствие permissions в манифесте.
        5. Применяет дифференциальный патч к ядру KRM.
        """
        pass
```

## 5. Дифференциальный Патч Мутаций (State Mutation Diff)
Чтобы плагин в песочнице не передавал целиком гигабайтные структуры данных обратно в ядро, он возвращает Mutation Delta (Diff) — набранный список выполненных атомарных операций:

```json
{
  "plugin_id": "plugin.org.chem_extractor",
  "applied_mutations": [
    {
      "op": "add_kg_entity",
      "entity": {
        "id": "ent_benzene_01",
        "name": "Benzene Ring",
        "entity_type": "concept_term"
      }
    },
    {
      "op": "add_kg_edge",
      "edge": {
        "source_id": "block_45a",
        "target_id": "ent_benzene_01",
        "relation_type": "mentions_entity",
        "confidence": 0.99
      }
    }
  ]
}
```

Ядро KAE валидирует Mutation Delta: если плагин попытался выполнить операцию, отсутствующую в его permissions (например, `op: "delete_krm_node"`), патч полностью отклоняется, а плагину присваивается статус ошибки execution failure.

## 6. Инварианты Плагинной Системы
1. **Контракт обратной совместимости (SemVer Matching):** Ядро KAE отказывает в загрузке плагина, если его требование `kae_core_version` не удовлетворяет текущей версии установленного движка.
2. **Гарантия изоляции OOM/Crash (Fail-Safe Isolation):** Падение процесса плагина по ошибке сегментации (Segmentation Fault), утечке памяти или исключению никак не влияет на работоспособность основного процесса KAE.
3. **Строгая валидация патчей (Zero-Trust Mutation Delta):** Ни одна мутация от стороннего плагина не применяется к ядру KRM/Graph без предварительной проверки манифеста прав в ядре.
