"""Debug-only: the raw print facts printed.measure_line reads off every
line TocAnalyzer reads a fixture from - height, stroke (and over height),
slant, colour, underline, and each face's likeness, regular / bold.

python3 tests/e2e/_debug_print_facts.py <pdf> [page]
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pymupdf

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.printed import STROKE_EM, measure_line, settle_page, size_in
from src.analyzers.toc.analyzer import _collect, _lines
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph

chain = []
for a in create_default_pipeline():
    if a.manifest.name == "TocAnalyzer":
        break
    chain.append(a)
doc = PdfSourceAdapter().parse(open(sys.argv[1], "rb"), f"file://{sys.argv[1]}")
PipelineRunner(chain).execute(doc, ReadingGraph(), KnowledgeGraph())
blocks = []
for r in doc.root_containers:
    _collect(r, blocks)
pages, _, _ = _lines(blocks)
src = pymupdf.open(sys.argv[1])
only = int(sys.argv[2]) if len(sys.argv) > 2 else None
for p, lines in sorted(pages.items()):
    if only is not None and p != only:
        continue
    page = src[p]
    pw, ph = page.rect.width, page.rect.height
    print(f"-- page {p}")
    facts = []
    for l in lines:
        m = measure_line(np, pymupdf, page, pymupdf.Rect(l.x0 * pw, l.y0 * ph, l.x1 * pw, l.y1 * ph), l.text)
        if m is None:
            print(f"   {l.text[:30]!r:32} no ink")
            continue
        m["text"] = l.text
        facts.append(m)
    settle_page(facts)
    for m in facts:
        reg = STROKE_EM[m["face"]][1 if m["italic"] else 0][0]
        ex = m["stroke"] / size_in(m["face"], m["height"], m["text"]) - reg
        print(f"   {m['text'][:30]!r:32} base {m['baseline']:6.1f} skew {m['skew']:+.4f} h {m['height']:5.2f} "
              f"st {m['stroke']:4.2f} ex {ex:+.3f} {m['face']} {'B' if m['bold'] else '-'}{'I' if m['italic'] else '-'} "
              f"fb {m['fakebold']:.1f} size {m['size']:5.2f} {'rgb' if m['rgb'] else ''}{'U' if m['underline'] else ''}")
