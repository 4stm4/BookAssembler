"""Debug-only: do the rebuild's horizontal rules land where the source's are?

Compares every drawn horizontal rule with the analyzer's own measured
list (table.metadata["rule_y"]), both taken relative to their first
rule. The overlay crops cannot answer this: they normalise both tables
to their text extent, which hides a uniform stretch and blames local
text placement on the rules.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts,
)
from tests.e2e._debug_crops import _output_table_rect
from tests.e2e._debug_row_height_solve import horizontal_rules
PH = 841.89
for name, fx in (("A", FIXTURE_A), ("B", FIXTURE_B)):
    t = _extract_table(fx)
    src = [y * PH for y in (t.metadata or {}).get("rule_y", [])]
    tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        rect = _output_table_rect(fitz, Path(pdf), 1, _table_texts(t))
        out = horizontal_rules(Path(pdf), 1, rect)
    s0, o0 = src[0], out[0]
    print(f"{name}: source {len(src)} rules, rebuild {len(out)}")
    n = min(len(src), len(out))
    diffs = [(o - o0) - (s - s0) for s, o in zip(src[:n], out[:n])]
    print("   diff pt:", " ".join(f"{d:+.1f}" for d in diffs))
    print(f"   within 1pt: {sum(abs(d) <= 1.0 for d in diffs)}/{n}   worst {max(abs(d) for d in diffs):.1f}pt")
