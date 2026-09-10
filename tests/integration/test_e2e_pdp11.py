"""
E2E integration test: PDP-11 Processor Handbook through full pipeline.

Builds a synthetic PDP-11-like document and runs the complete pipeline
including the pdp11 skill pack. Verifies:
- Pipeline runs without exceptions
- Expected block types are produced
- KG entities are extracted
- LaTeX assembles without errors
- Chunker produces valid chunks
"""
import json
import os
import hashlib
from pathlib import Path
from typing import Dict, List

import pytest

from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.ai_layer.chunker import SemanticChunker
from src.assembler.latex_builder import build_latex
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    AlgorithmBlock,
    BibEntryBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    EphemeraBlock,
    FigureBlock,
    FootnoteBlock,
    FormulaBlock,
    IndexEntryBlock,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    NormalizedRect,
    ParagraphBlock,
    SidebarBlock,
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
    TitlePageBlock,
    TocEntryBlock,
    VisualLayout,
)
from src.skills.runner import SkillPack, SkillsRunner


def _span(text: str) -> StyledTextSpan:
    return StyledTextSpan(text=text)


def _para(text: str, page: int = 0, y0: float = 0.2, y1: float = 0.3) -> ParagraphBlock:
    inline = TextLineInline(spans=[_span(text)])
    vl = VisualLayout(
        page_or_screen_index=page,
        bounding_box=NormalizedRect(x0=0.1, y0=y0, x1=0.9, y1=y1),
    )
    p = ParagraphBlock(inlines=[inline], visual_layout=vl)
    p.extraction_confidence = 0.7
    p.classification_confidence = 0.7
    return p


def _build_pdp11_doc() -> KnowledgeDocument:
    """Build a synthetic PDP-11 document with representative content."""

    # Title page
    title_para = _para("PDP-11 PROCESSOR HANDBOOK", page=0, y0=0.3, y1=0.4)

    # Page number (ephemera)
    pagenum = _para("1", page=0, y0=0.01, y1=0.04)

    # Header (ephemera)
    header = _para("Chapter 1", page=1, y0=0.01, y1=0.04)

    # TOC entries
    toc1 = _para("Introduction ..................... 1", page=1, y0=0.15, y1=0.18)
    toc2 = _para("Processor Architecture .......... 5", page=1, y0=0.19, y1=0.22)
    toc3 = _para("Instruction Set ................. 15", page=1, y0=0.23, y1=0.26)
    toc4 = _para("Memory Management ............... 30", page=1, y0=0.27, y1=0.30)

    # Chapter content
    intro = _para(
        "The PDP-11 is a series of 16-bit minicomputers sold by "
        "Digital Equipment Corporation (DEC) from 1970.",
        page=2, y0=0.15, y1=0.25,
    )

    # Register description (instruction-like)
    reg_desc = _para(
        "R0 through R5 are general-purpose registers. R6 is the Stack Pointer (SP), "
        "R7 is the Program Counter (PC).",
        page=3, y0=0.15, y1=0.25,
    )

    # Assembly listing
    asm_para = _para(
        "MOV R0, R1\nADD #10, R2\nCMP R3, R4\nBEQ DONE\nJMP START",
        page=4, y0=0.15, y1=0.30,
    )

    # Formula
    formula_para = _para(
        "Address = Base + 2 * Index",
        page=5, y0=0.15, y1=0.20,
    )

    # Footnote-like
    footnote_para = _para(
        "1) The PDP-11/70 also supports 22-bit addressing.",
        page=5, y0=0.90, y1=0.95,
    )

    # Bibliography entry
    bib_para = _para(
        "[1] DEC, PDP-11 Architecture Handbook, 1979.",
        page=8, y0=0.15, y1=0.20,
    )

    # Algorithm
    algo_para = _para(
        "Algorithm 1: Memory allocation\nif free_pages > 0 then allocate else wait end",
        page=6, y0=0.15, y1=0.30,
    )

    # Index entries
    idx1 = _para("Addressing modes, 15, 20-25", page=9, y0=0.15, y1=0.18)
    idx2 = _para("Stack pointer, 8, 12", page=9, y0=0.19, y1=0.22)

    # Build containers
    toc_container = ContainerUnit(
        title="Contents", level=1,
        children=[toc1, toc2, toc3, toc4],
    )

    ch1 = ContainerUnit(
        title="Introduction", level=1,
        children=[intro, reg_desc],
    )

    ch2 = ContainerUnit(
        title="Instruction Set", level=1,
        children=[asm_para, formula_para, footnote_para],
    )

    ch3 = ContainerUnit(
        title="Memory Management", level=1,
        children=[algo_para],
    )

    bib_container = ContainerUnit(
        title="Bibliography", level=1,
        semantic_type="bibliography",
        children=[bib_para],
    )

    index_container = ContainerUnit(
        title="Index", level=1,
        children=[idx1, idx2],
    )

    doc = KnowledgeDocument(
        title="PDP-11 Processor Handbook",
        source_uri="benchmark/corpora/pdp11-handbook.pdf",
        root_containers=[
            ContainerUnit(title="", level=0, children=[pagenum, title_para, header]),
            toc_container,
            ch1, ch2, ch3,
            bib_container,
            index_container,
        ],
    )
    doc.metadata = {"languages": ["english"]}
    return doc


class TestE2EPDP11:
    def test_full_pipeline_no_exceptions(self):
        doc = _build_pdp11_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        pr = PipelineRunner(pipeline)
        pr.execute(doc, rg, kg)

    def test_block_type_counts(self):
        doc = _build_pdp11_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        pr = PipelineRunner(pipeline)
        pr.execute(doc, rg, kg)

        counts: Dict[str, int] = {}

        def _count(node):
            name = type(node).__name__
            counts[name] = counts.get(name, 0) + 1
            for child in getattr(node, "children", []):
                _count(child)
            for child in getattr(node, "content", []):
                _count(child)

        for c in doc.root_containers:
            _count(c)

        assert counts.get("ContainerUnit", 0) >= 5
        assert counts.get("EphemeraBlock", 0) >= 1
        assert counts.get("AlgorithmBlock", 0) >= 1
        assert counts.get("IndexEntryBlock", 0) >= 1

    def test_kg_entities_extracted(self):
        doc = _build_pdp11_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        pr = PipelineRunner(pipeline)
        pr.execute(doc, rg, kg)

        entity_names = [e.name for e in kg._entities.values()]
        assert len(entity_names) > 0

    def test_latex_builds(self):
        doc = _build_pdp11_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        pr = PipelineRunner(pipeline)
        pr.execute(doc, rg, kg)

        tex = build_latex(doc)
        assert r"\documentclass" in tex
        assert r"\end{document}" in tex
        assert len(tex) > 500

    def test_chunker_produces_chunks(self):
        doc = _build_pdp11_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()
        pipeline = runner.build_pipeline(pack)
        pr = PipelineRunner(pipeline)
        pr.execute(doc, rg, kg)

        chunker = SemanticChunker()
        chunks = chunker.build_chunks(doc, rg, kg)
        assert len(chunks) >= 3
        types = {c.chunk_type for c in chunks}
        assert len(types) >= 2

    def test_skill_pack_matches(self):
        doc = _build_pdp11_doc()
        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        assert pack.matches(doc)

    def test_deterministic_latex(self):
        """Same doc through pipeline twice → same LaTeX."""
        doc1 = _build_pdp11_doc()
        doc2 = _build_pdp11_doc()
        rg1, rg2 = ReadingGraph(), ReadingGraph()
        kg1, kg2 = KnowledgeGraph(), KnowledgeGraph()

        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        runner = SkillsRunner()

        for doc, rg, kg in [(doc1, rg1, kg1), (doc2, rg2, kg2)]:
            pipeline = runner.build_pipeline(pack)
            pr = PipelineRunner(pipeline)
            pr.execute(doc, rg, kg)

        tex1 = build_latex(doc1)
        tex2 = build_latex(doc2)
        assert tex1 == tex2


class TestRegressionBaseline:
    """Guards the fixture's shape against silent drift.

    This used to be `test_save_baseline`: it overwrote
    benchmark/baselines/pdp11-2026-08-31.json on every run and asserted only
    that the file existed. That destroyed the snapshot instead of comparing
    against it — and the snapshot was of the real handbook (202 paragraphs),
    while this test builds a synthetic fixture (a dozen), so the two never
    described the same document. Nothing else reads that path, so the write
    only ever lost data.

    The baseline now lives beside the test, describes this fixture, and is
    read, not written. Regenerate deliberately after an intended change:

        KAE_UPDATE_BASELINE=1 pytest tests/integration/test_e2e_pdp11.py
    """

    BASELINE = Path("tests/integration/baselines/pdp11-fixture.json")

    @staticmethod
    def _measure() -> Dict[str, object]:
        doc = _build_pdp11_doc()
        rg, kg = ReadingGraph(), KnowledgeGraph()
        pack = SkillPack.from_file(Path("skills/pdp11.yaml"))
        pr = PipelineRunner(SkillsRunner().build_pipeline(pack))
        pr.execute(doc, rg, kg)

        counts: Dict[str, int] = {}

        def _count(node):
            name = type(node).__name__
            counts[name] = counts.get(name, 0) + 1
            for child in getattr(node, "children", []):
                _count(child)

        for c in doc.root_containers:
            _count(c)

        tex = build_latex(doc)
        return {
            "block_counts": counts,
            "kg_entity_count": len(kg._entities),
            "kg_edge_count": len(kg._edges),
            "latex_length": len(tex),
            "latex_hash": hashlib.sha256(tex.encode()).hexdigest(),
        }

    def test_fixture_matches_baseline(self):
        current = self._measure()

        if os.environ.get("KAE_UPDATE_BASELINE"):
            self.BASELINE.parent.mkdir(parents=True, exist_ok=True)
            self.BASELINE.write_text(
                json.dumps(current, indent=2, sort_keys=True) + "\n")
            pytest.skip("baseline regenerated on request")

        assert self.BASELINE.exists(), (
            f"{self.BASELINE} is missing; regenerate with "
            "KAE_UPDATE_BASELINE=1 and commit it"
        )
        expected = json.loads(self.BASELINE.read_text())

        # Counts first: they name what drifted, while the hash only says
        # that something did.
        assert current["block_counts"] == expected["block_counts"]
        assert current["kg_entity_count"] == expected["kg_entity_count"]
        assert current["kg_edge_count"] == expected["kg_edge_count"]
        assert current["latex_hash"] == expected["latex_hash"], (
            "LaTeX changed while the block counts did not — a rendering "
            "change, not a detection one"
        )

    def test_the_real_handbook_snapshot_is_not_touched(self):
        """The benchmark snapshot is data, not an output of this test."""
        snapshot = Path("benchmark/baselines/pdp11-2026-08-31.json")
        before = snapshot.read_bytes()
        self._measure()
        assert snapshot.read_bytes() == before
