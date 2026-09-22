"""Debug-only: compare the OLD envelope-based row height (max(y1s) -
min(y0s) across all of a row's cells) against the NEW per-cell max, for
both fixtures, to find which row(s) the recent latex_builder.py change
affects most. Run with python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table


def _cell_bb(cell):
    vl = getattr(cell, "visual_layout", None)
    return getattr(vl, "bounding_box", None) if vl else None


def report(name, fixture):
    table = _extract_table(fixture)
    print(f"--- {name} ---")
    for i, row in enumerate(table.grid):
        y0s, y1s, per_cell = [], [], []
        for cell in row:
            bb = _cell_bb(cell)
            if bb is not None:
                y0s.append(bb.y0)
                y1s.append(bb.y1)
                per_cell.append(bb.y1 - bb.y0)
        if not y0s:
            continue
        envelope = max(y1s) - min(y0s)
        new_max = max(per_cell)
        if abs(envelope - new_max) > 1e-6:
            print(f"row {i}: envelope={envelope:.5f} new_max={new_max:.5f} diff={envelope-new_max:.5f}")


report("FIXTURE_A", FIXTURE_A)
report("FIXTURE_B", FIXTURE_B)
