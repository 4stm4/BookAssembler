"""
SkillsRunner — compose analyzers from YAML skill packs (RFC 0006).

A skill pack is a YAML file that lists analyzer steps and an apply_when
condition. The runner builds a filtered pipeline from the default analyzers,
enabling/disabling specific ones per the skill pack configuration.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.analyzers.base import BaseAnalyzer
from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import KnowledgeDocument
from src.skills.dsl import DSLContext, evaluate

log = logging.getLogger(__name__)


def _build_context(doc: KnowledgeDocument) -> DSLContext:
    page_count = 0
    for c in doc.root_containers:
        for child in getattr(c, "children", []):
            vl = getattr(child, "visual_layout", None)
            if vl and hasattr(vl, "page_or_screen_index"):
                page_count = max(page_count, vl.page_or_screen_index + 1)
    languages = (doc.metadata or {}).get("languages", [])
    if isinstance(languages, str):
        languages = [languages]
    return DSLContext(
        title=doc.title or "",
        source_uri=doc.source_uri or "",
        page_count=page_count,
        languages=languages,
        metadata=doc.metadata or {},
        text_sample=doc.title or "",
    )


class SkillPack:
    """Parsed YAML skill pack."""

    def __init__(
        self,
        name: str,
        version: str,
        apply_when: str,
        steps: List[str],
        disabled: Optional[List[str]] = None,
        requires: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.version = version
        self.apply_when = apply_when
        self.steps = steps
        self.disabled = disabled or []
        self.requires = requires or {}
        self.metadata = metadata or {}

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "SkillPack":
        data = yaml.safe_load(yaml_text) or {}
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            apply_when=data.get("apply_when", "true"),
            steps=data.get("steps", []),
            disabled=data.get("disabled", []),
            requires=data.get("requires", {}),
            metadata=data,
        )

    @classmethod
    def from_file(cls, path: Path) -> "SkillPack":
        return cls.from_yaml(path.read_text(encoding="utf-8"))

    def matches(self, doc: KnowledgeDocument) -> bool:
        ctx = _build_context(doc)
        try:
            return evaluate(self.apply_when, ctx)
        except Exception:
            log.warning("Failed to evaluate apply_when for skill %s", self.name)
            return False


class SkillsRunner:
    """Builds and runs a filtered pipeline from a skill pack."""

    def __init__(self) -> None:
        self._packs: Dict[str, SkillPack] = {}

    def load_pack(self, path: Path) -> SkillPack:
        pack = SkillPack.from_file(path)
        self._packs[pack.name] = pack
        return pack

    def load_directory(self, directory: Path) -> List[SkillPack]:
        packs: List[SkillPack] = []
        if not directory.exists():
            return packs
        for f in sorted(directory.glob("*.yaml")):
            try:
                packs.append(self.load_pack(f))
            except Exception as e:
                log.warning("Failed to load skill pack %s: %s", f, e)
        return packs

    @property
    def packs(self) -> Dict[str, SkillPack]:
        return dict(self._packs)

    def build_pipeline(self, pack: SkillPack) -> List[BaseAnalyzer]:
        default = create_default_pipeline()
        name_to_analyzer = {type(a).__name__: a for a in default}

        if pack.steps:
            pipeline: List[BaseAnalyzer] = []
            for step_name in pack.steps:
                analyzer = name_to_analyzer.get(step_name)
                if analyzer is not None:
                    pipeline.append(analyzer)
                else:
                    log.warning("Skill %s references unknown analyzer: %s", pack.name, step_name)
        else:
            pipeline = list(default)

        if pack.disabled:
            disabled_set = set(pack.disabled)
            pipeline = [a for a in pipeline if type(a).__name__ not in disabled_set]

        return pipeline

    def run(
        self,
        pack: SkillPack,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        pipeline = self.build_pipeline(pack)
        runner = PipelineRunner(pipeline)
        runner.execute(doc, rg, kg, context)
