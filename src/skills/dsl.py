"""
apply_when DSL evaluator for Skills (RFC 0006).

Supported predicates:
  contains(field, value)   — field contains substring
  equals(field, value)     — field == value
  in(value, field)         — value in list-field
  matches(field, regex)    — regex match on field
  page_count > N           — document page count comparison
  has_language(lang)       — document has given language

Combinators: and, or, not
"""

import re
from typing import Any, Callable, Dict, List, Optional


class DSLError(Exception):
    pass


class DSLContext:
    """Evaluation context built from a KnowledgeDocument."""

    def __init__(
        self,
        title: str = "",
        source_uri: str = "",
        page_count: int = 0,
        languages: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        text_sample: str = "",
    ) -> None:
        self.title = title
        self.source_uri = source_uri
        self.page_count = page_count
        self.languages = languages or []
        self.metadata = metadata or {}
        self.text_sample = text_sample

    def get_field(self, name: str) -> Any:
        if name == "title":
            return self.title
        if name == "source_uri":
            return self.source_uri
        if name == "page_count":
            return self.page_count
        if name == "languages":
            return self.languages
        if name == "text_sample":
            return self.text_sample
        return self.metadata.get(name, "")


def _tokenize(expr: str) -> List[str]:
    tokens: List[str] = []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c in " \t\n\r":
            i += 1
            continue
        if c in "(),><=!":
            if c in "><=!" and i + 1 < len(expr) and expr[i + 1] == "=":
                tokens.append(expr[i : i + 2])
                i += 2
            else:
                tokens.append(c)
                i += 1
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < len(expr) and expr[j] != c:
                j += 1
            tokens.append(expr[i + 1 : j])
            i = j + 1
            continue
        j = i
        while j < len(expr) and expr[j] not in " \t\n\r(),><=!'\"":
            j += 1
        tokens.append(expr[i:j])
        i = j
    return tokens


def evaluate(expr: str, ctx: DSLContext) -> bool:
    tokens = _tokenize(expr)
    result, _ = _parse_or(tokens, 0, ctx)
    return result


def _parse_or(tokens: List[str], pos: int, ctx: DSLContext) -> tuple:
    left, pos = _parse_and(tokens, pos, ctx)
    while pos < len(tokens) and tokens[pos] == "or":
        pos += 1
        right, pos = _parse_and(tokens, pos, ctx)
        left = left or right
    return left, pos


def _parse_and(tokens: List[str], pos: int, ctx: DSLContext) -> tuple:
    left, pos = _parse_not(tokens, pos, ctx)
    while pos < len(tokens) and tokens[pos] == "and":
        pos += 1
        right, pos = _parse_not(tokens, pos, ctx)
        left = left and right
    return left, pos


def _parse_not(tokens: List[str], pos: int, ctx: DSLContext) -> tuple:
    if pos < len(tokens) and tokens[pos] == "not":
        pos += 1
        val, pos = _parse_atom(tokens, pos, ctx)
        return not val, pos
    return _parse_atom(tokens, pos, ctx)


def _parse_atom(tokens: List[str], pos: int, ctx: DSLContext) -> tuple:
    if pos >= len(tokens):
        raise DSLError("Unexpected end of expression")

    tok = tokens[pos]

    if tok == "(":
        pos += 1
        val, pos = _parse_or(tokens, pos, ctx)
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        return val, pos

    if tok == "contains":
        pos += 1  # (
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
        field = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ",":
            pos += 1
        value = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        field_val = str(ctx.get_field(field))
        return value.lower() in field_val.lower(), pos

    if tok == "equals":
        pos += 1
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
        field = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ",":
            pos += 1
        value = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        return str(ctx.get_field(field)) == value, pos

    if tok == "in":
        pos += 1
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
        value = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ",":
            pos += 1
        field = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        field_val = ctx.get_field(field)
        if isinstance(field_val, list):
            return value in field_val, pos
        return value in str(field_val), pos

    if tok == "matches":
        pos += 1
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
        field = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ",":
            pos += 1
        pattern = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        field_val = str(ctx.get_field(field))
        return bool(re.search(pattern, field_val)), pos

    if tok == "has_language":
        pos += 1
        if pos < len(tokens) and tokens[pos] == "(":
            pos += 1
        lang = tokens[pos]; pos += 1
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        return lang.lower() in [l.lower() for l in ctx.languages], pos

    if tok == "page_count":
        pos += 1
        op = tokens[pos]; pos += 1
        val = int(tokens[pos]); pos += 1
        pc = ctx.page_count
        if op == ">":
            return pc > val, pos
        if op == ">=":
            return pc >= val, pos
        if op == "<":
            return pc < val, pos
        if op == "<=":
            return pc <= val, pos
        if op in ("==", "="):
            return pc == val, pos
        raise DSLError(f"Unknown operator: {op}")

    if tok in ("true", "True"):
        return True, pos + 1
    if tok in ("false", "False"):
        return False, pos + 1

    raise DSLError(f"Unknown token: {tok}")
