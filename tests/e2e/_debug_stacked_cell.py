"""Debug-only: a stacked cell of a fixture's table - its box, its lines as
the analyzer joined them, the page's words in it grouped by printed line
(with each line's y), and the pitch the builder sets them at.

python3 tests/e2e/_debug_stacked_cell.py <pdf> <a word in the cell>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import pymupdf

from src.analyzers.table.rules import _cell_text_of
from src.assembler.latex_builder import build_latex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import _extract_table

pdf, needle = Path(sys.argv[1]), sys.argv[2]
table = _extract_table(pdf)
page = pymupdf.open(pdf)[0]
pw, ph = page.rect.width, page.rect.height
cell = next(c for r in table.grid for c in r if needle in _cell_text_of(c))
b = cell.visual_layout.bounding_box
print(f"box y {b.y0 * ph:.1f}..{b.y1 * ph:.1f}  x {b.x0 * pw:.1f}..{b.x1 * pw:.1f}")
print("metadata keys", sorted((cell.metadata or {}).keys()))
words = [w for w in page.get_text("words")
         if b.x0 * pw - 1 <= (w[0] + w[2]) / 2 <= b.x1 * pw + 1 and b.y0 * ph - 1 <= (w[1] + w[3]) / 2 <= b.y1 * ph + 1]
lines = []
for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
    c = (w[1] + w[3]) / 2
    if lines and abs(c - lines[-1][0]) < 0.5 * (w[3] - w[1]):
        lines[-1][1].append(w)
    else:
        lines.append([c, [w]])
for c, ws in lines:
    print(f"  y {min(w[1] for w in ws):6.1f}..{max(w[3] for w in ws):6.1f}  {' '.join(w[4] for w in sorted(ws, key=lambda w: w[0]))[:70]}")
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]))
i = tex.find(needle)
print(tex[max(0, i - 300):i + 200])
