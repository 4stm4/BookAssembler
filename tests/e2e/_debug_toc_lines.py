"""Debug-only: the lines TocAnalyzer reads a fixture's contents from - each
with its page, box and size, and the block types the pipeline left there.

python3 tests/e2e/_debug_toc_lines.py <pdf>
"""
import sys
from collections import Counter

sys.path.insert(0, "/app")

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.toc.analyzer import _collect, _lines
from src.analyzers.toc.layout import read_toc
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph

chain = []
for a in create_default_pipeline():
    if a.manifest.name == "TocAnalyzer":
        break
    chain.append(a)
print("chain", [a.manifest.name for a in chain])
doc = PdfSourceAdapter().parse(open(sys.argv[1], "rb"), f"file://{sys.argv[1]}")
PipelineRunner(chain).execute(doc, ReadingGraph(), KnowledgeGraph())

types = Counter()
def walk(n):
    for c in getattr(n, "children", []):
        types[(type(c).__name__, bool(getattr(c, "is_tombstoned", False)))] += 1
        walk(c)
for r in doc.root_containers:
    walk(r)
print("blocks", dict(types))

blocks = []
for r in doc.root_containers:
    _collect(r, blocks)
pages, _, _ = _lines(blocks)
for p, lines in sorted(pages.items()):
    print(f"-- page {p}")
    for l in lines:
        print(f"  {l.x0 * 595:6.1f} {l.y0 * 842:6.1f} {l.x1 * 595:6.1f} {l.y1 * 842:6.1f} {l.size:4.1f}  {l.text[:70]!r}")
toc = read_toc(pages)
print("entries", len(toc.entries))
