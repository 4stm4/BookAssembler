"""Debug-only: the LaTeX the product assembles for a contents fixture,
page by page (page_aware), the lines that hold a given text.

python3 tests/e2e/_debug_toc_tex.py <pdf> <text>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from src.assembler.latex_builder import build_latex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_toc_overlay import _extract_tocs

tocs = _extract_tocs(Path(sys.argv[1]))
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=tocs)]),
                  page_aware=True)
for line in tex.splitlines():
    if sys.argv[2] in line:
        print(line[:400])
