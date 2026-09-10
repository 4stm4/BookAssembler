"""SemVer requirement matching for plugin loading (RFC 0010 §6.1).

Hand-rolled because the project pins no packaging/semver dependency.
"""

import re
from typing import Tuple

_CLAUSE_RE = re.compile(r"^(>=|<=|==|!=|>|<)?\s*(\d+(?:\.\d+){0,2})$")

Version = Tuple[int, int, int]


def parse_version(text: str) -> Version:
    """Parse ``MAJOR[.MINOR[.PATCH]]`` into a comparable triple."""
    parts = (text or "").strip().split(".")
    if not parts or not all(p.isdigit() for p in parts) or len(parts) > 3:
        raise ValueError(f"Malformed version: {text!r}")
    numbers = [int(p) for p in parts] + [0, 0]
    return numbers[0], numbers[1], numbers[2]


def _matches(version: Version, op: str, target: Version) -> bool:
    if op == ">=":
        return version >= target
    if op == "<=":
        return version <= target
    if op == ">":
        return version > target
    if op == "<":
        return version < target
    if op == "!=":
        return version != target
    return version == target


def satisfies(version: str, spec: str) -> bool:
    """True if ``version`` satisfies every comma-separated clause of ``spec``.

    An empty spec or ``*`` accepts any version. Raises ValueError on a malformed
    spec so a typo in plugin.yaml surfaces instead of silently accepting.
    """
    spec = (spec or "").strip()
    if not spec or spec == "*":
        return True

    current = parse_version(version)
    for clause in spec.split(","):
        clause = clause.strip()
        if not clause:
            continue
        match = _CLAUSE_RE.match(clause)
        if match is None:
            raise ValueError(f"Malformed version spec clause: {clause!r}")
        if not _matches(current, match.group(1) or "==", parse_version(match.group(2))):
            return False
    return True
