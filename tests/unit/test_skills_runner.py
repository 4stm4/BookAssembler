"""Tests for SkillsRunner and SkillPack (RFC 0006)."""
import tempfile
from pathlib import Path

import pytest

from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock
from src.skills.runner import SkillPack, SkillsRunner


_PACK_YAML = """\
name: test-pack
version: "1.0.0"
description: "Test skill pack"
apply_when: "contains(title, 'Test')"
requires:
  kae: ">=0.4.0"
steps:
  - NormalizationAnalyzer
  - ReadingOrderAnalyzer
  - HeadingAnalyzer
disabled:
  - CalloutDetectorAnalyzer
"""


class TestSkillPackParsing:
    def test_basic_fields(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        assert pack.name == "test-pack"
        assert pack.version == "1.0.0"
        assert pack.apply_when == "contains(title, 'Test')"

    def test_steps(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        assert "NormalizationAnalyzer" in pack.steps
        assert len(pack.steps) == 3

    def test_disabled(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        assert "CalloutDetectorAnalyzer" in pack.disabled

    def test_requires(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        assert pack.requires.get("kae") == ">=0.4.0"


class TestSkillPackMatching:
    def test_matches_true(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        doc = KnowledgeDocument(title="Test Document")
        assert pack.matches(doc)

    def test_matches_false(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        doc = KnowledgeDocument(title="Other Document")
        assert not pack.matches(doc)


class TestSkillsRunner:
    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(_PACK_YAML)
            f.flush()
            runner = SkillsRunner()
            pack = runner.load_pack(Path(f.name))
            assert pack.name == "test-pack"
            assert "test-pack" in runner.packs

    def test_load_directory(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "test.yaml").write_text(_PACK_YAML)
            runner = SkillsRunner()
            packs = runner.load_directory(Path(td))
            assert len(packs) == 1
            assert packs[0].name == "test-pack"

    def test_build_pipeline_with_steps(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        names = [type(a).__name__ for a in pipeline]
        assert "NormalizationAnalyzer" in names
        assert "HeadingAnalyzer" in names
        assert len(pipeline) == 3

    def test_build_pipeline_disabled(self):
        yaml_text = """\
name: disabled-test
version: "1.0.0"
apply_when: "true"
steps: []
disabled:
  - CalloutDetectorAnalyzer
  - TheoremDetectorAnalyzer
"""
        pack = SkillPack.from_yaml(yaml_text)
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        names = [type(a).__name__ for a in pipeline]
        assert "CalloutDetectorAnalyzer" not in names
        assert "TheoremDetectorAnalyzer" not in names
        assert "NormalizationAnalyzer" in names

    def test_run_minimal(self):
        pack = SkillPack.from_yaml(_PACK_YAML)
        runner = SkillsRunner()
        doc = KnowledgeDocument(
            title="Test",
            root_containers=[ContainerUnit(title="Ch1", level=1)],
        )
        rg = ReadingGraph()
        kg = KnowledgeGraph()
        runner.run(pack, doc, rg, kg)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as td:
            runner = SkillsRunner()
            packs = runner.load_directory(Path(td))
            assert len(packs) == 0


class TestBuiltinPacks:
    def test_pdp11_loads(self):
        path = Path("skills/pdp11.yaml")
        if not path.exists():
            pytest.skip("pdp11.yaml not found")
        pack = SkillPack.from_file(path)
        assert pack.name == "pdp11"
        assert "TheoremDetectorAnalyzer" in pack.disabled

    def test_pdf_lit_loads(self):
        path = Path("skills/pdf-lit.yaml")
        if not path.exists():
            pytest.skip("pdf-lit.yaml not found")
        pack = SkillPack.from_file(path)
        assert pack.name == "pdf-lit"

    def test_math_book_loads(self):
        path = Path("skills/math-book.yaml")
        if not path.exists():
            pytest.skip("math-book.yaml not found")
        pack = SkillPack.from_file(path)
        assert pack.name == "math-book"
        assert "has_language" in pack.apply_when

    def test_pdp11_matches(self):
        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        doc = KnowledgeDocument(title="PDP-11 Processor Handbook")
        assert pack.matches(doc)
        doc2 = KnowledgeDocument(title="Algebra Textbook")
        assert not pack.matches(doc2)
