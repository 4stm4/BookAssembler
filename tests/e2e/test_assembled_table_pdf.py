"""E2E: tables from two different real PDF sources, assembled into one PDF.

Fixtures:
  - z80_decimal_binary_table.pdf   (Fig. 1.2, clean text layer, one table)
  - z80_voltage_regulator_table.pdf (messier OCR'd text layer, several tables)

Both go through the real extraction chain (PdfSourceAdapter ->
TableDetectorAnalyzer, same as tests/e2e/test_krm_roundtrip.py) to get a real
TableBlock each. Those two TableBlocks, from two unrelated source files, are
placed under two containers of one KnowledgeDocument and rendered through the
real assembler (src/assembler/latex_builder.build_latex) - this is the
opposite direction from the roundtrip test: KRM -> LaTeX, not PDF -> KRM.

The LaTeX-text assertions run everywhere - build_latex needs no external
toolchain. The actual XeLaTeX compilation (RFC 0021 SS4: guaranteed only in
the locked Docker image, texlive:*-frozen) is attempted too; a local
TeX Live missing a package (this Mac's "basic" scheme lacks mdframed's
`framed.sty`) skips that half explicitly rather than failing or silently
passing, so it still runs for real wherever the locked toolchain is - a real
Docker/rpi5 environment.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers.table import TableDetectorAnalyzer
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, TableBlock

FIXTURES = Path(__file__).parent.parent / "fixtures"
FIXTURE_A = FIXTURES / "z80_decimal_binary_table.pdf"
FIXTURE_B = FIXTURES / "z80_voltage_regulator_table.pdf"


def _extract_table(pdf_path: Path, index: int = 0) -> TableBlock:
    doc = PdfSourceAdapter().parse(open(pdf_path, "rb"), f"file://{pdf_path}")
    container = doc.root_containers[0]
    TableDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    tables = [
        c for c in container.children
        if isinstance(c, TableBlock) and not c.is_tombstoned
    ]
    assert tables, f"no live TableBlock extracted from {pdf_path.name}"
    return tables[index]


@pytest.fixture(scope="module")
def two_source_doc() -> KnowledgeDocument:
    table_a = _extract_table(FIXTURE_A)
    # index 0: the nA7812 spec table (28 rows once merged - see
    # tests/e2e/test_krm_roundtrip.py history: this fixture was also used to
    # catch a prose false-positive, a fragmentation regression, and the
    # adjacent-table-merge fix in _merge_adjacent_tables).
    table_b = _extract_table(FIXTURE_B, index=0)

    return KnowledgeDocument(
        title="Two Sources",
        root_containers=[
            ContainerUnit(title="Decimal-Binary Table", level=1, children=[table_a]),
            ContainerUnit(title="Voltage Regulator Spec", level=1, children=[table_b]),
        ],
    )


def test_latex_contains_both_source_tables(two_source_doc):
    """build_latex must render both tables, atomically, with nothing dropped."""
    tex = build_latex(two_source_doc)

    assert tex.count("\\begin{tabular}") == 2, "expected one tabular per source table"

    # A cell from the decimal-binary table (Fig. 1.2).
    assert "00000000" in tex
    assert "00100000" in tex
    # A cell from the voltage-regulator spec table. The descriptive
    # paragraph above it ("jiA7812 ELECTRICAL CHARACTERISTICS: ...") is
    # prose, not a table row - TableDetectorAnalyzer now trims exactly that
    # kind of leading single-cell, sentence-length block off a detected
    # run (src/analyzers/table/analyzer.py _process_container) instead of
    # folding it into the table, so it correctly does not appear here.
    assert "Output Voltage" in tex
    assert "CONDITIONS" in tex


def test_assembled_pdf_compiles_and_keeps_both_tables(two_source_doc):
    """Full round trip: two real PDFs -> two TableBlocks -> one LaTeX doc ->
    one compiled PDF, and the compiled PDF's own text still has both."""
    fitz = pytest.importorskip("pymupdf")

    tex = build_latex(two_source_doc)

    with tempfile.TemporaryDirectory() as work_dir:
        tex_path = os.path.join(work_dir, "book.tex")
        with open(tex_path, "w") as fh:
            fh.write(tex)

        try:
            pdf_path = compile_xelatex(tex_path, work_dir)
        except RuntimeError as exc:
            if "not found" in str(exc):
                pytest.skip(
                    "local TeX Live is missing a package the preamble needs "
                    "(RFC 0021 SS4: compilation is only guaranteed in the "
                    f"locked Docker image) - {exc}"
                )
            raise

        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 0

        compiled = fitz.open(pdf_path)
        full_text = "".join(page.get_text() for page in compiled)
        compiled.close()

        assert "00000000" in full_text
        # See test_latex_contains_both_source_tables: "7812" only ever
        # appeared via the descriptive paragraph above the table, which
        # TableDetectorAnalyzer now correctly excludes as prose, not a row.
        assert "Output Voltage" in full_text
        assert "CONDITIONS" in full_text
