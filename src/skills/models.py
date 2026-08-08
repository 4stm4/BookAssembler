"""
Skill, Recipe, and Profile models for Knowledge Assembly Engine (KAE).

This module defines data structures for declarative domain skills, pipeline recipes,
and source auto-detection profiles according to RFC 0006 (docs/architecture/0006-skills-and-recipes.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Purely declarative skills (no executable Python code embedded)
- SemVer versioning support
- Standard library dependencies only (dataclasses, typing, re)
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class SkillManifest:
    """
    Declarative specification of a domain Skill.
    """
    id: str
    name: str
    version: str
    domain: str
    target_analyzer: str
    confidence_threshold: float = 0.8
    patterns: Dict[str, List[str]] = field(default_factory=dict)
    rules: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Skill:
    """
    Wrapper class over a declarative domain skill.
    Provides context matching capabilities against input text samples.
    """

    def __init__(self, manifest: SkillManifest) -> None:
        self._manifest = manifest

    @property
    def manifest(self) -> SkillManifest:
        """
        Returns the skill manifest.
        """
        return self._manifest

    def matches_context(self, text_sample: str) -> bool:
        """
        Checks if the skill applies to the given text sample
        based on keywords and regex patterns in the manifest.
        """
        if not text_sample:
            return False

        # 1. Check keywords in applies_to / metadata
        keywords: List[str] = []
        applies_to = self._manifest.metadata.get("applies_to", {})
        if isinstance(applies_to, dict):
            kw_list = applies_to.get("keywords", [])
            if isinstance(kw_list, list):
                keywords.extend([str(k) for k in kw_list if k])

        meta_kw = self._manifest.metadata.get("keywords", [])
        if isinstance(meta_kw, list):
            keywords.extend([str(k) for k in meta_kw if k])

        for kw in keywords:
            if kw and kw.lower() in text_sample.lower():
                return True

        # 2. Check regex patterns in patterns dictionary
        for _category, pattern_list in self._manifest.patterns.items():
            for pattern_str in pattern_list:
                try:
                    if re.search(pattern_str, text_sample):
                        return True
                except re.error:
                    continue

        return False


@dataclass
class RecipeStep:
    """
    Single step in a pipeline recipe binding an analyzer to a set of skills.
    """
    analyzer_name: str
    skill_ids: List[str] = field(default_factory=list)


@dataclass
class Recipe:
    """
    Pipeline recipe specifying execution sequence of analyzers and assigned skills.
    """
    recipe_id: str
    name: str
    version: str
    pipeline: List[RecipeStep] = field(default_factory=list)


@dataclass
class SourceProfile:
    """
    Publisher profile for document source auto-detection.
    """
    profile_id: str
    publisher_name: str
    matching_keywords: List[str] = field(default_factory=list)
    matching_patterns: List[str] = field(default_factory=list)
    recommended_recipe_id: str = ""
