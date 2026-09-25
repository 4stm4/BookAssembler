"""Debug-only: the outer rules we draw, and what each emitted row costs.

Three questions, one probe, because the same build answers all three:

1. Which outer verticals does the source draw? The voltage-regulator
   fixture's scan records no table_rule_x0, yet we used to emit "|"
   there - a rule 124pt left of the source's leftmost.

2. Is a column wide enough for the ink it holds? p{Xcm} IS the text
   width and \tabcolsep sits outside it, so a column's footprint is
   p{} + 2*tabcolsep. An earlier version of this probe subtracted
   tabcolsep from p{} as well and reported columns four times too
   narrow.

3. Why is a row taller than its source step? This prints the REAL
   emitted tabular body - each row's \tabularnewline[Xpt] and whether
   its text carries an internal line break - beside the step the
   source actually printed. A row that costs 14pt where the source
   stepped 4.6pt is carrying a cell _merge_orphan_rows folded several
   printed lines into.

Note that table.grid is the analyzer's RAGGED structure: a short row's
cells sit at list positions that do not name their columns. The
builder resolves that itself by snapping each cell's x0 to the nearest
column bin, so a cell's index in grid says nothing about which LaTeX
column it ends up in - do not read misplacement from grid alone.

Run with python3, not pytest.
"""
import re
import sys

sys.path.insert(0, "/app")

from src.assembler.latex_builder import build_latex, _cell_text
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_A4_W_PT = 595.276
_A4_H_PT = 841.89
_PT_PER_CM = 28.3465


def _bbox(cell):
    return getattr(getattr(cell, "visual_layout", None), "bounding_box", None)


def _row_y0(row):
    y0s = [_bbox(c).y0 for c in row if _bbox(c) is not None]
    return min(y0s) if y0s else None


def run(name, fixture):
    print("=" * 78)
    print(name)
    table = _extract_table(fixture)
    md = getattr(table, "metadata", None) or {}
    bb = table.visual_layout.bounding_box

    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    spec = next((l.strip() for l in tex.splitlines() if "begin{tabular}" in l), "")
    m = re.search(r"tabcolsep\}\{([0-9.]+)pt\}", tex)
    tabcolsep = float(m.group(1)) if m else 0.0
    ours = [float(w) * _PT_PER_CM for w in re.findall(r"p\{([0-9.]+)cm\}", spec)]
    m = re.search(r"arraystretch\}\{([0-9.]+)\}", tex)
    print(f"  tabcolsep {tabcolsep:.2f}pt   arraystretch {m.group(1) if m else '?'}")
    # Every DISTINCT \fontsize in the emitted body: the second argument
    # is the line box each cell is actually set with, which is what a
    # row can be compressed to. Reading only the first match hides a
    # per-cell command that disagrees with the table-level one.
    _fs = sorted(set(re.findall(r"\\fontsize\{[0-9.]+\}\{[0-9.]+\}", tex)))
    print(f"  emitted fontsize commands ({len(_fs)}): {' '.join(_fs[:12])}")
    # The air emitted under the top rule. On fixture A the source puts
    # its header separator 21.9pt below its top rule and we put ours at
    # 26.0pt - if this vskip accounts for that 4.1pt, it is being added
    # on top of a row height that already carried it.
    _vsk = re.findall(r"\\noalign\{\\vskip ([0-9.]+)pt\}", tex)
    print(f"  emitted \\noalign vskip: {_vsk if _vsk else 'none'}")
    print(f"  table_rule_x0={md.get('table_rule_x0')}  x1={md.get('table_rule_x1')}")
    _ph = 841.89
    for _k in ("table_rule_y0", "table_rule_y1"):
        _v = md.get(_k)
        print(f"  {_k} = {_v}" + (f"  ({_v * _ph:.1f}pt)" if _v else ""))

    rule_x = md.get("column_rule_x") or []
    left = md.get("table_rule_x0")
    right = md.get("table_rule_x1")
    bounds_pt = [
        b * _A4_W_PT
        for b in (
            [left if left is not None else bb.x0] + list(rule_x)
            + [right if right is not None else bb.x1]
        )
    ]
    print("  col   source   our p{}   footprint   widest ink")
    for c in range(len(bounds_pt) - 1):
        our_w = ours[c] if c < len(ours) else float("nan")
        widest = max(
            (
                (_bbox(row[c]).x1 - _bbox(row[c]).x0) * _A4_W_PT
                for row in table.grid
                if c < len(row) and _bbox(row[c]) is not None
            ),
            default=0.0,
        )
        print(
            f"  {c:<5} {bounds_pt[c + 1] - bounds_pt[c]:6.1f}   {our_w:6.1f}   "
            f"{our_w + 2 * tabcolsep:9.1f}  {widest:10.1f}"
        )

    # The source's own row steps, from the grid's geometry.
    y0s = [_row_y0(row) for row in table.grid]
    steps = []
    for i in range(len(y0s)):
        nxt = y0s[i + 1] if i + 1 < len(y0s) else None
        steps.append(
            (nxt - y0s[i]) * _A4_H_PT if (nxt is not None and y0s[i] is not None) else None
        )

    body = [
        l for l in tex.splitlines()
        if "tabularnewline" in l
    ]
    print(f"  emitted rows: {len(body)}   grid rows: {len(table.grid)}")
    print("  row   src step   emitted extra   text")
    for i, line in enumerate(body):
        m = re.search(r"tabularnewline\[(-?[0-9.]+)pt\]", line)
        extra = f"{float(m.group(1)):+6.2f}" if m else "     -"
        src = steps[i] if i < len(steps) else None
        src_s = f"{src:6.1f}" if src is not None else "     -"
        text = re.sub(r"\\[a-zA-Z]+\*?(\[[^]]*\])?(\{[^}]*\})?", " ", line)
        text = " ".join(text.replace("&", " | ").split())[:54]
        print(f"  {i:<5} {src_s}     {extra}   {text}")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
