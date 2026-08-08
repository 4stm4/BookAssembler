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
