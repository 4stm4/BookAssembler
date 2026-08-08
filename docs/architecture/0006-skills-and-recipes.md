# RFC 0006: Skills & Recipes Specification

| Статус | Версия | Дата | Автор |
|---|---|---|---|
| Draft | 1.0.0 | 2026-08-07 | Core Architecture Team |

## 1. Назначение и концепция
Документ описывает архитектуру слоя Skills & Recipes.

Главная проблема классических анализаторов — попытка зашить все частные случаи и правила конкретных издательств или производителей (Intel, Motorola, IEEE, Microsoft Press) прямо в код анализатора. Это приводит к раздуванию кода, жесткой связности и ложным срабатываниям на документах других типов.

В Knowledge Assembly Engine (KAE) разделены механика анализа и доменная экспертиза:
- **Analyzer (Анализатор)** — исполняемый движок (код Python), реализующий базовый алгоритм и контролирующий права доступа.
- **Skill (Навык)** — декларативный модуль (Markdown/YAML), содержащий специфичные паттерны, регулярные выражения, словари и промпты для описания конкретных конструкций.
- **Recipe (Рецепт)** — конфигурация, связывающая набор анализаторов и навыков в единый исполнительный пайплайн.
- **Profile (Профиль)** — правила автоопределения источника (например, «если в документе встречаются паттерны Intel 8086, задействовать рецепт Intel Manuals»).

```
                      [ Profile: Intel Manuals ]
                                  │
                                  ▼
                     [ Recipe: Technical Book ]
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      ▼                           ▼                           ▼
[ LayoutAnalyzer ]       [ CaptionAnalyzer ]         [ CodeSyntaxAnalyzer ]
      │                           │                           │
      └── ( Skill: Intel Layout ) └── ( Skill: Intel Caption ) └── ( Skill: x86 Asm )
```

## 2. Спецификация Навыка (Skill Format)
Каждый Skill представляет собой стандартизированный Markdown-файл с YAML-заголовком (Frontmatter), расположенный в структуре `skills/<domain>/<skill_name>.md`.

### 2.1. Формат декларации Навыка (`skills/intel/x86_asm_listings.md`)
```yaml
---
id: "skill.intel.x86_asm_listings"
name: "Intel x86 Assembly Listing Recognizer"
version: "1.0.0"
domain: "intel"
target_analyzer: "CodeSyntaxAnalyzer"
description: "Паттерны и мнемоники для распознавания листингов ассемблера x86 в документации Intel."
applies_to:
  publishers: ["Intel Corporation"]
  keywords: ["MOV", "INT", "PUSH", "POP", "REGISTER"]
confidence_threshold: 0.85
---

# Intel x86 Assembly Listing Recognizer

## Patterns

### Registers
- `(?i)\b(AX|BX|CX|DX|SI|DI|BP|SP|CS|DS|SS|ES|IP|FLAGS)\b`
- `(?i)\b(AH|AL|BH|BL|CH|CL|DH|DL)\b`

### Mnemonics
- `(?i)\b(MOV|ADD|SUB|INC|DEC|CMP|JMP|JE|JNE|CALL|RET|NOP|INT|CLI|STI)\b`

### Hex Numbers
- `\b[0-9A-FA-F]+H\b`

## Rules
1. Если текстовый блок содержит более 2 мнемоник из списка и шестнадцатеричные числа вида `0FFH`, маркировать блок как `programming_language = "asm_x86"`.
2. Операнды в квадратных скобках `[BX+SI]` классифицировать как косвенную адресацию памяти.
```

### 2.2. Загрузка и привязка Навыка в коде
Анализаторы получают список применимых навыков от ядра и используют их конфигурацию для выполнения задач.

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class SkillManifest:
    id: str
    name: str
    version: str
    domain: str
    target_analyzer: str
    confidence_threshold: float = 0.8
    patterns: Dict[str, List[str]] = field(default_factory=dict)
    rules: List[str] = field(default_factory=list)

class BaseSkill:
    def __init__(self, manifest: SkillManifest):
        self.manifest = manifest

    def matches_context(self, text_sample: str) -> bool:
        """Проверка применимости навыка к текущему фрагменту текста."""
        # Логика первичной валидации по ключевым словам
        return True
```

## 3. Спецификация Рецепта (Recipe Specification)
Recipe задает точный порядок запуска анализаторов и подключает к ним конкретные навыки.

```yaml
# recipes/intel_technical_manual.yaml
recipe_id: "recipe.intel_technical_manual"
name: "Intel Technical Documentation Pipeline"
version: "1.0.0"

pipeline:
  - analyzer: "NormalizationAnalyzer"
    skills: []

  - analyzer: "LayoutAnalyzer"
    skills:
      - "skill.intel.layout_grid"

  - analyzer: "HeadingAnalyzer"
    skills:
      - "skill.intel.section_numbering"

  - analyzer: "CaptionAnalyzer"
    skills:
      - "skill.intel.figure_captions"

  - analyzer: "CodeSyntaxAnalyzer"
    skills:
      - "skill.intel.x86_asm_listings"

  - analyzer: "CrossLinkAnalyzer"
    skills:
      - "skill.generic.cross_references"
```

## 4. Спецификация Профиля и Автоопределения (Profile Specification)
Profile занимается сканированием первичного Unprocessed KRM и выбором оптимального рецепта.

```python
@dataclass
class SourceProfile:
    profile_id: str
    publisher_name: str
    matching_rules: List[str]  # Набор правил для автоопределения
    recommended_recipe_id: str

class ProfileResolver:
    """Определяет подходящий профиль на основе сигнатур в документе."""
    def resolve(self, doc: "KnowledgeDocument") -> str:
        # Анализ первых страниц, метаданных и шрифтов
        # Если найдены характерные признаки -> возвращается recipe_id
        return "recipe.intel_technical_manual"
```

## 5. Изоляция и Версионирование Навыков
1. **Безопасность:** Навык является чисто декларативным (данные, регулярные выражения, промпты). Ему категорически запрещено содержать исполняемый Python-код.
2. **Версионирование:** Все навыки хранят точную версию (SemVer). Изменение логики навыка требует повышения версии (v1.0.0 -> v1.1.0), что гарантирует воспроизводимость обработки старых документов.
3. **Обратная связь (Confidence Feedback):** Если навык возвращает оценку уверенности ниже `confidence_threshold`, анализатор игнорирует его рекомендации и откатывается к универсальным (Generic) правилам.
