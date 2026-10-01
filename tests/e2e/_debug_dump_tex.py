"""Debug-only: print the tabular the real pipeline emits for a fixture.

Run with python3 (argument A or B), not pytest.
"""
import sys
sys.path.insert(0, "/app")
from src.assembler.latex_builder import build_latex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

from pathlib import Path
arg = (sys.argv[1:] or ["A"])[0]
fx = FIXTURE_A if arg == "A" else FIXTURE_B if arg == "B" else Path(arg)
t = _extract_table(fx)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
start = tex.index("\\begin{tabular}")
print(tex[tex.rfind("\n", 0, start - 400):tex.index("\\end{tabular}") + 14])
