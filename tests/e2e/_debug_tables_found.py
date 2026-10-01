"""Debug-only: every table the real extraction finds on a fixture, with
its rows, and every leftover paragraph on the page with its position.

Run with python3 (argument A or B), not pytest.
"""
import sys
sys.path.insert(0, "/app")
from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers.table import TableDetectorAnalyzer
from src.assembler.latex_builder import _cell_text
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ParagraphBlock, TableBlock
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B

PH = 841.89
from pathlib import Path
arg = (sys.argv[1:] or ["A"])[0]
fx = FIXTURE_A if arg == "A" else FIXTURE_B if arg == "B" else Path(arg)
doc = PdfSourceAdapter().parse(open(fx, "rb"), f"file://{fx}")
TableDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
for child in doc.root_containers[0].children:
    if getattr(child, "is_tombstoned", False):
        continue
    bb = child.visual_layout.bounding_box if child.visual_layout else None
    where = f"y {bb.y0 * PH:6.1f}..{bb.y1 * PH:6.1f}" if bb else ""
    if isinstance(child, TableBlock):
        print(f"TABLE {where} rows {len(child.grid)}")
        for row in child.grid:
            print("    " + " | ".join(_cell_text(c).strip()[:16] for c in row))
    elif isinstance(child, ParagraphBlock):
        text = " / ".join("".join(s.text for s in i.spans) for i in child.inlines)
        print(f"PARA  {where} {text[:90]}")
    else:
        print(type(child).__name__, where)
