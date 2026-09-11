"""How the TOC layout reads given pages of a bench book.

  python3 -m benchmark.toc.debug --books DIR <book> <page>[,<page>...]

Pages are 0-based physical indices. Runs the pipeline up to the analyzer
before TocAnalyzer, then prints, per page: column edges, rows (x0, page
label, text), the entries read and whether the contents stopped there; then
the whole contents as read_toc assembles it.
"""
import argparse
import logging
import os

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers import create_default_pipeline
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.toc import analyzer as A
from src.analyzers.toc import layout as L
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph


def main() -> None:
    ap = argparse.ArgumentParser(description="TOC layout, page by page.")
    ap.add_argument("--books", required=True, help="directory holding <book>.pdf")
    ap.add_argument("book")
    ap.add_argument("pages", help="0-based page indices, comma-separated")
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    pages = [int(p) for p in args.pages.split(",")]

    with open(os.path.join(args.books, f"{args.book}.pdf"), "rb") as f:
        doc = PdfSourceAdapter().parse(f, f"test://{args.book}.pdf")
    chain = []
    for a in create_default_pipeline():
        if a.manifest.name == "TocAnalyzer":
            break
        chain.append(a)
    PipelineRunner(chain).execute(doc, ReadingGraph(), KnowledgeGraph())

    blocks = []
    for c in doc.root_containers:
        A._collect(c, blocks)
    by_page, _, _ = A._lines(blocks)

    print("headings:", [(h.page, round(h.y0, 3), h.text) for h in L.find_headings(by_page)])
    for pg in pages:
        lines = by_page.get(pg, [])
        print(f"\n======== page {pg}: {len(lines)} lines")
        edges = L.column_edges(lines)
        print("edges:", [round(e, 3) for e in edges])
        for edge, col in zip(edges, L._columns(lines, edges)):
            kept = L._drop_side_labels(col, edge)
            print(f"-- column edge={edge:.3f}: {len(col)} lines, {len(col) - len(kept)} dropped as side labels")
            for r in L._rows(kept, edge):
                print(f"   x0={r.x0:.3f} y0={r.y0:.3f} size={r.size:.1f} page={r.page_label!s:6} | {r.text}")
        read = L.read_page(lines)
        print(f"read_page: entries={len(read.entries)} rows={read.rows} stopped={read.stopped}")
        for e in read.entries:
            print(f"   L{e.level} {e.number_and_title()} -> {e.page_label}"
                  + (f"   [desc: {' / '.join(e.description)[:60]}]" if e.description else ""))

    toc = L.read_toc(by_page)
    print(f"\nread_toc: heading={toc.heading.text if toc.heading else None} "
          f"pages={toc.pages} entries={len(toc.entries)}")
    for e in toc.entries:
        print(f" TOC L{e.level} {e.number_and_title()} -> {e.page_label}")


if __name__ == "__main__":
    main()
