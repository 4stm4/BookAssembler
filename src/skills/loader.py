"""
Skill and Profile loader implementation for Knowledge Assembly Engine (KAE).

This module provides SkillLoader for parsing declarative Markdown skill files
with YAML Frontmatter and ProfileResolver for document source auto-detection
according to RFC 0006 (docs/architecture/0006-skills-and-recipes.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Safe lightweight YAML Frontmatter parsing (no PyYAML / external dependencies)
- Recursive Markdown skill loading from directories
- Standard library dependencies only (dataclasses, typing, pathlib, re)
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from src.krm.models import KnowledgeDocument
from src.skills.models import (
    Skill,
    SkillManifest,
    SourceProfile,
)


def _parse_yaml_value(val_str: str) -> Any:
    """
    Parses a single scalar or inline list YAML value.
    """
    val_str = val_str.strip()
    if val_str.startswith("[") and val_str.endswith("]"):
        inner = val_str[1:-1].strip()
        if not inner:
            return []
        return [s.strip().strip("\"'") for s in inner.split(",") if s.strip()]
    if (val_str.startswith('"') and val_str.endswith('"')) or (
        val_str.startswith("'") and val_str.endswith("'")
    ):
        return val_str[1:-1]
    if val_str.lower() == "true":
        return True
    if val_str.lower() == "false":
        return False
    try:
        if "." in val_str:
            return float(val_str)
        return int(val_str)
    except ValueError:
        return val_str


def _parse_yaml_frontmatter(yaml_str: str) -> Dict[str, Any]:
    """
    Lightweight YAML Frontmatter parser supporting key-value pairs, inline lists, and nested objects.
    """
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_dict: Dict[str, Any] = result

    for line in yaml_str.splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if ":" in line_stripped and not line_stripped.startswith("- "):
            parts = line_stripped.split(":", 1)
            key = parts[0].strip().strip("\"'")
            val_str = parts[1].strip()

            if indent == 0:
                current_dict = result

            if not val_str:
                new_dict: Dict[str, Any] = {}
                current_dict[key] = new_dict
                current_key = key
                current_dict = new_dict
            else:
                current_dict[key] = _parse_yaml_value(val_str)
                current_key = key
        elif line_stripped.startswith("- "):
            val = _parse_yaml_value(line_stripped[2:].strip())
            if current_key and current_key in current_dict:
                if not isinstance(current_dict[current_key], list):
                    current_dict[current_key] = []
                current_dict[current_key].append(val)

    return result


def _parse_markdown_body(body_str: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    Parses Markdown sections (## Patterns and ## Rules) from skill markdown body.
    """
    patterns: Dict[str, List[str]] = {}
    rules: List[str] = []

    current_section: Optional[str] = None
    current_category: str = "General"

    for line in body_str.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("## Patterns"):
            current_section = "patterns"
            current_category = "General"
            continue
        elif stripped.startswith("## Rules"):
            current_section = "rules"
            continue
        elif (
            stripped.startswith("## ")
            and not stripped.startswith("## Patterns")
            and not stripped.startswith("## Rules")
        ):
            current_section = None
            continue

        if current_section == "patterns":
            if stripped.startswith("### "):
                current_category = stripped[4:].strip()
            elif stripped.startswith("- ") or stripped.startswith("* "):
                pat_text = stripped[2:].strip()
                if pat_text.startswith("`") and pat_text.endswith("`") and len(pat_text) >= 2:
                    pat_text = pat_text[1:-1]
                patterns.setdefault(current_category, []).append(pat_text)
        elif current_section == "rules":
            rule_match = re.match(r"^(?:\d+\.|\-|\*)\s+(.*)$", stripped)
            if rule_match:
                rules.append(rule_match.group(1).strip())

    return patterns, rules


class SkillLoader:
    """
    Loader class responsible for parsing Markdown skill files and directories into Skill objects.
    """

    @staticmethod
    def load_skill_from_markdown(file_path: Path | str) -> Skill:
        """
        Parses a single Markdown file containing YAML Frontmatter into a Skill object.
        """
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(
                f"Invalid Skill file format in '{path}': missing YAML frontmatter enclosed in '---'."
            )

        frontmatter_str = parts[1]
        body_str = parts[2]

        fm_data = _parse_yaml_frontmatter(frontmatter_str)
        patterns, rules = _parse_markdown_body(body_str)

        manifest = SkillManifest(
            id=str(fm_data.get("id", path.stem)),
            name=str(fm_data.get("name", path.stem)),
            version=str(fm_data.get("version", "1.0.0")),
            domain=str(fm_data.get("domain", "generic")),
            target_analyzer=str(fm_data.get("target_analyzer", "")),
            confidence_threshold=float(fm_data.get("confidence_threshold", 0.8)),
            patterns=patterns,
            rules=rules,
            metadata=fm_data,
        )

        return Skill(manifest=manifest)

    @staticmethod
    def load_skills_from_dir(directory_path: Path | str) -> Dict[str, Skill]:
        """
        Recursively scans a directory and loads all .md skill files into a dictionary keyed by skill ID.
        """
        dir_path = Path(directory_path)
        skills: Dict[str, Skill] = {}

        if not dir_path.exists() or not dir_path.is_dir():
            return skills

        for file_path in dir_path.rglob("*.md"):
            try:
                skill = SkillLoader.load_skill_from_markdown(file_path)
                skills[skill.manifest.id] = skill
            except Exception:
                continue

        return skills


class ProfileResolver:
    """
    Auto-detects the matching publisher profile and recommended recipe ID for a KnowledgeDocument.
    """

    def _extract_doc_text_sample(self, doc: KnowledgeDocument, max_length: int = 5000) -> str:
        """
        Extracts sample text from document metadata, title, and first containers.
        """
        text_parts: List[str] = []
        if doc.title:
            text_parts.append(doc.title)
        if doc.source_uri:
            text_parts.append(doc.source_uri)

        def _collect_text(node: Any) -> None:
            if len(" ".join(text_parts)) >= max_length:
                return
            if hasattr(node, "title") and getattr(node, "title"):
                text_parts.append(str(getattr(node, "title")))
            if hasattr(node, "text") and getattr(node, "text"):
                text_parts.append(str(getattr(node, "text")))
            if hasattr(node, "inlines") and getattr(node, "inlines"):
                for inline in getattr(node, "inlines"):
                    if hasattr(inline, "spans"):
                        for span in getattr(inline, "spans"):
                            if hasattr(span, "text") and getattr(span, "text"):
                                text_parts.append(str(getattr(span, "text")))
            if hasattr(node, "children") and getattr(node, "children"):
                for child in getattr(node, "children"):
                    _collect_text(child)
            if hasattr(node, "root_containers") and getattr(node, "root_containers"):
                for container in getattr(node, "root_containers"):
                    _collect_text(container)

        _collect_text(doc)
        return " ".join(text_parts)

    def resolve(
        self, doc: KnowledgeDocument, profiles: List[SourceProfile]
    ) -> Optional[str]:
        """
        Scans KnowledgeDocument and resolves the recommended_recipe_id from the best matching profile.
        Returns None if no profile matches.
        """
        doc_sample = self._extract_doc_text_sample(doc)
        if not doc_sample:
            return None

        best_score = 0
        best_recipe_id: Optional[str] = None

        for profile in profiles:
            score = 0
            if profile.publisher_name and profile.publisher_name.lower() in doc_sample.lower():
                score += 2

            for kw in profile.matching_keywords:
                if kw and kw.lower() in doc_sample.lower():
                    score += 1

            for pat in profile.matching_patterns:
                try:
                    if re.search(pat, doc_sample):
                        score += 2
                except re.error:
                    continue

            if score > best_score:
                best_score = score
                best_recipe_id = profile.recommended_recipe_id

        return best_recipe_id
