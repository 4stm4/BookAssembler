"""Debug-only: a fixture through the adapter, the table detector and the
caption analyzer, then the assembler - the caption block found, what it
links to, and the LaTeX around the table's end.

python3 tests/e2e/_debug_caption_tex.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers.caption.analyzer import CaptionAnalyzer
from src.analyzers.table import TableDetectorAnalyzer
from src.assembler.latex_builder import build_latex
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import CaptionBlock, TableBlock

pdf = Path(sys.argv[1])
doc = PdfSourceAdapter().parse(open(pdf, "rb"), f"file://{pdf}")
TableDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
CaptionAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
for child in doc.root_containers[0].children:
    if child.is_tombstoned:
        continue
    if isinstance(child, CaptionBlock):
        print("caption:", child.caption_text, "->", child.target_id if hasattr(child, "target_id") else getattr(child, "caption_of", None))
    if isinstance(child, TableBlock):
        print("table", child.id, "caption_id", child.caption_id)
tex = build_latex(doc)
end = tex.rfind("\\end{tabular}")
print(tex[end:end + 400])
