"""Debug-only: why does a row not get the rule above it?

The voltage-regulator fixture's source draws 20 horizontal rules and we
emit 17, and its header carries border_bottom but not border_top even
though its source prints a rule 5.3pt above the header text. The
decision is one line in _mark_cell_borders:

    border_top = above is not None and (box.y0 - above) <= reach

so this prints its three inputs per cell - the box, the nearest rule
each side, and the reach - rather than reasoning about them.

Run with python3, not pytest.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table.rules import _BORDER_MATCH_FLOOR
from src.assembler.latex_builder import _cell_text
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_PH = 841.89


def run(name, fixture, rows=3):
    print("=" * 74)
    print(name)
    table = _extract_table(fixture)
    doc = pymupdf.open(str(fixture))
    page = doc[table.visual_layout.page_or_screen_index or 0]

    # Re-derive the rules the same way _mark_cell_borders does, by
    # calling it on a copy and reading what it stored.
    md = getattr(table, "metadata", None) or {}
    print(f"  stored rule_y0={md.get('table_rule_y0')} rule_y1={md.get('table_rule_y1')}")
    print(f"  _BORDER_MATCH_FLOOR = {_BORDER_MATCH_FLOOR} "
          f"({_BORDER_MATCH_FLOOR * _PH:.2f}pt)")
    doc.close()

    for r in range(min(rows, len(table.grid))):
        for c, cell in enumerate(table.grid[r]):
            vl = getattr(cell, "visual_layout", None)
            box = getattr(vl, "bounding_box", None) if vl else None
            if box is None:
                continue
            h = box.y1 - box.y0
            reach = max(h, _BORDER_MATCH_FLOOR)
            print(
                f"  r{r} c{c}  y {box.y0 * _PH:7.2f}..{box.y1 * _PH:7.2f} "
                f"h {h * _PH:5.2f}pt  reach {reach * _PH:5.2f}pt  "
                f"top={getattr(cell, 'border_top', None)} "
                f"bot={getattr(cell, 'border_bottom', None)}  "
                f"{_cell_text(cell).strip()[:18]}"
            )


run("FIXTURE_B (voltage regulator)", FIXTURE_B)
run("FIXTURE_A (decimal/binary)", FIXTURE_A)
