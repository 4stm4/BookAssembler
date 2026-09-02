"""entity: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re
from src.graph.knowledge_graph import EntityType, KGEntityNode, KnowledgeGraph, RelationType

_REGISTER_RE = re.compile(r"\b(R1[0-5]|R[0-9])\b")

_INSTRUCTION_RE = re.compile(
    r"\b(MOV|ADD|SUB|MUL|DIV|LDR|STR|CMP|BNE|BEQ|BGT|BLT|BGE|BLE|"
    r"AND|ORR|EOR|LSL|LSR|ASR|NOP|SWI|SVC|BL|BX|PUSH|POP|LDM|STM)\b"
)

_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")

_PATTERNS = [
    (_REGISTER_RE, EntityType.REGISTER),
    (_INSTRUCTION_RE, EntityType.INSTRUCTION),
    (_HEX_RE, EntityType.CONCEPT_TERM),
]
