"""Debug-only: a fixture page's blocks as the adapter makes them and as the
whole pipeline leaves them - type, box, lines - to see where a paragraph
is split or merged.

python3 tests/e2e/_debug_page_blocks.py <pdf> [adapter|pipeline] [lines] [printed] [words]
"""
import sys

sys.path.insert(0, "/app")
from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit

doc = PdfSourceAdapter().parse(open(sys.argv[1], "rb"), f"file://{sys.argv[1]}")
if (sys.argv[2:] or ["adapter"])[0] == "pipeline":
    PipelineRunner(create_default_pipeline()).execute(doc, ReadingGraph(), KnowledgeGraph())


def walk(node, depth=0):
    if isinstance(node, ContainerUnit):
        print("  " * depth + f"[{node.semantic_type or 'container'}] {node.title!r}")
        for c in node.children:
            walk(c, depth + 1)
        return
    vl = node.visual_layout
    b = vl.bounding_box if vl else None
    box = f"{b.x0 * 595:5.0f}{b.y0 * 842:5.0f}{b.x1 * 595:5.0f}{b.y1 * 842:5.0f}" if b else "-"
    lines = [" ".join(s.text for s in il.spans if hasattr(s, "text")) for il in getattr(node, "inlines", []) or []]
    dead = f" (tombstoned: {(node.metadata or {}).get('tombstone_reason')})" if node.is_tombstoned else ""
    print("  " * depth + f"{type(node).__name__}{dead} {box}  {len(lines)} lines: {(lines[0] if lines else '')[:50]!r} .. {(lines[-1] if lines else '')[-30:]!r}")
    if "lines" in sys.argv[3:]:
        for il, text in zip(getattr(node, "inlines", []) or [], lines):
            lb = il.visual_layout.bounding_box if getattr(il, "visual_layout", None) else None
            at = f"{lb.x0 * 595:5.0f}{lb.y0 * 842:5.0f}{lb.x1 * 595:5.0f}{lb.y1 * 842:5.0f}" if lb else "-"
            print("  " * depth + f"    {at}  {text[:70]!r}")
    if "printed" in sys.argv[3:]:
        for pl in (node.metadata or {}).get("printed_lines", []):
            x0, y0, x1, y1 = pl["box"]
            print("  " * depth + f"    ink {x0 * 595:6.1f}{y0 * 842:6.1f}{x1 * 595:6.1f}{y1 * 842:6.1f} base {pl['baseline'] * 842:6.1f}"
                  f" size {pl['size']:5.2f} {pl['face']} bold={pl['bold']} italic={pl['italic']} skew={pl['skew']:+.4f} {pl['text'][:40]!r}"
                  + "".join(f" over[{a * 595:.1f}-{b * 595:.1f}@{y * 842:.1f}]" for a, b, y, _ in pl.get("overlines") or []))
            if "words" in sys.argv[3:]:
                print("  " * depth + "      " + " ".join(
                    f"{w[2]}[{w[0] * 595:.1f}-{w[1] * 595:.1f}]" + ("".join(k[0].upper() for k in ("bold", "italic") if len(w) > 4 and w[4].get(k)))
                    + (f"~{w[4]['miss']:.2f}" if len(w) > 4 and "miss" in w[4] else "")
                    + ("#INK" if len(w) > 4 and w[4].get("ink") else "")
                    for w in pl["words"]))


for r in doc.root_containers:
    walk(r)
