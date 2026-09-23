"""Debug-only: which outer vertical rules does the source actually draw,
and which ones do we emit?

_debug_col_rules.py showed the voltage-regulator fixture's source drawing
five verticals spanning 191.8pt while the rebuild draws six spanning
318.0pt. Dropping our leftmost leaves widths that match the source's to
about a point, so the whole -436px "shift" looks like one outer frame
rule the source never drew.

This prints, per fixture, the stored rule metadata beside the column
spec the real builder emits, so the "|" we put in the spec can be read
against the rules the scan actually found.

Run with python3, not pytest.
"""
import re
import sys

sys.path.insert(0, "/app")

from src.assembler.latex_builder import build_latex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table


def run(name, fixture):
    print("=" * 60)
    print(name)
    table = _extract_table(fixture)
    md = getattr(table, "metadata", None) or {}
    bb = table.visual_layout.bounding_box

    print(f"  bb.x0={bb.x0:.4f}  bb.x1={bb.x1:.4f}  (page fractions)")
    for key in (
        "table_rule_x0", "table_rule_x1", "table_rule_y0", "table_rule_y1",
        "column_rule_x",
    ):
        print(f"  {key} = {md.get(key)}")

    first = table.grid[0] if table.grid else []
    print(f"  grid: {len(table.grid)} rows x {len(first)} cols")
    for edge in ("border_left", "border_right", "border_top", "border_bottom"):
        flags = [bool(getattr(c, edge, False)) for c in first]
        print(f"  header row {edge}: {flags}")

    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    for line in tex.splitlines():
        if "begin{tabular}" in line:
            print(f"  col_spec: {line.strip()}")
            break
    m = re.search(r"arrayrulewidth\}\{([^}]+)\}", tex)
    if m:
        print(f"  arrayrulewidth: {m.group(1)}")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
