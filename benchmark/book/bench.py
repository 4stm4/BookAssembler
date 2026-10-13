"""Book bench: how well a whole book comes back out of the engine.

Takes what the product itself made of a book - the document the pipeline
read (GET /api/v1/jobs/<id>/result) and the PDF the page-aware build set
of it (POST .../assemble/preview) - and lays it against the source PDF,
page by page. Nothing here reads, analyzes or builds the book: a wrapper
that did would measure itself.

    python3 -m benchmark.book.bench --source book.pdf --rebuilt preview_pages.pdf \\
        --result result.json --out report_dir

What it measures, per source page and over the book:

- pages     the rebuilt pages each source page came out as (by their text),
            and the pages that ran onto a second;
- text      how much of the page's text is in the rebuild (its letters'
            runs of four, in whatever order the lines come);
- blocks    each block of the source's text found in the rebuild by its
            words and laid over it as ink - the paragraph test's measure
            (tests/e2e/test_paragraph_overlay._paragraph_mismatch);
- figures,  each figure and table the document holds, cut out of the source
  tables    by its place and out of the rebuild by its place against the
            nearest block found there, laid over one another - the figure
            test's measure (tests/e2e/test_figure_overlay._laid_over);
- headings  the book's own contents against the document's headings: the
            entries a heading answers, the entries linked to a page.

It writes report.json, report.md and, for the worst pages by each measure
and every nth page, a sheet of the source page beside its rebuild to look
at - a number says a page is off, not what is wrong with it.
"""

import argparse
import difflib
import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymupdf as fitz
from PIL import Image

from tests.e2e.test_figure_overlay import _laid_over
from tests.e2e.test_paragraph_overlay import _paragraph_mismatch, _paragraph_rect, _run_on_page
from tests.e2e.test_visual_overlay import _render_crop

GRAM = 4               # letters in a run a page's text is compared by
MIN_BLOCK_WORDS = 5    # a block of fewer words is no measure of a paragraph
LIMIT = 0.10           # the overlay tests' share of ink allowed to miss
TITLE_LIKENESS = 0.85  # as the heading test matches a title
SHEETS_WORST = 8
SHEET_EVERY = 10
SHEET_ZOOM = 1.3


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", text.lower())


def _grams(page) -> Dict[str, int]:
    """A page's text as its lines' runs of GRAM letters, counted: a word
    the rebuild sets letter by letter reads apart ("F igure"), and a page
    read in columns comes in another order - the runs inside a line stay."""
    out: Dict[str, int] = {}
    for line in page.get_text("text").splitlines():
        s = _letters(line)
        for k in range(len(s) - GRAM + 1):
            out[s[k:k + GRAM]] = out.get(s[k:k + GRAM], 0) + 1
    return out


def _shared(a: Dict[str, int], b: Dict[str, int]) -> int:
    return sum(min(n, b.get(g, 0)) for g, n in a.items())


def map_pages(src, out) -> List[List[int]]:
    """Which rebuilt pages each source page came out as: the rebuild keeps
    the book's order, so each rebuilt page is the source page, from the
    last one matched on, that shares the most text with it; one with no
    text of its own goes with the page before it."""
    src_grams = [_grams(p) for p in src]
    pages: List[List[int]] = [[] for _ in src]
    at = 0
    for j, page in enumerate(out):
        grams = _grams(page)
        if sum(grams.values()) >= 20:
            reach = range(at, min(len(src), at + 6))
            best = max(reach, key=lambda i: _shared(grams, src_grams[i]) / (1 + sum(grams.values())))
            if _shared(grams, src_grams[best]) >= 0.2 * sum(grams.values()):
                at = best
        pages[at].append(j)
    return pages


def text_recall(src_page, out_pages) -> Optional[float]:
    """The share of a source page's text found on the pages it came out as;
    None where the page has too little text to say."""
    want = _grams(src_page)
    total = sum(want.values())
    if total < 20:
        return None
    have: Dict[str, int] = {}
    for page in out_pages:
        for g, n in _grams(page).items():
            have[g] = have.get(g, 0) + n
    return _shared(want, have) / total


def block_overlays(src_path: Path, out_path: Path, src_page, page_index: int, out, out_pages: List[int]) -> List[Dict]:
    """Each block of a source page's text laid over the rebuild: where it
    was found there (by its words, on the page of its own where found
    best), and how much of its ink misses."""
    found = []
    for block in src_page.get_text("blocks"):
        words = (block[4] or "").split()
        if block[6] != 0 or len(words) < MIN_BLOCK_WORDS:
            continue
        src_run = _run_on_page(src_page, words)
        runs = [(j, _run_on_page(out[j], words)) for j in out_pages]
        runs = [(j, r) for j, r in runs if r]
        entry: Dict[str, Any] = {"text": " ".join(words)[:60], "words": len(words), "found": bool(src_run and runs)}
        if src_run and runs:
            j, out_run = max(runs, key=lambda jr: len(jr[1]))
            src_rect, out_rect = _paragraph_rect(fitz, src_page, src_run), _paragraph_rect(fitz, out[j], out_run)
            if src_rect is not None and out_rect is not None and not src_rect.is_empty and not out_rect.is_empty:
                entry.update(page=j, src=list(src_rect), out=list(out_rect), mismatch=_paragraph_mismatch(
                    _render_crop(fitz, src_path, page_index, src_rect), _render_crop(fitz, out_path, j, out_rect)))
            else:
                entry["found"] = False
        found.append(entry)
    return found


def region_overlay(src_path: Path, out_path: Path, page_index: int, src_page, box: List[float],
                   blocks: List[Dict]) -> Optional[float]:
    """A figure's or a table's place on a source page (box, shares of the
    page) laid over the rebuild, cut there by its place against the
    nearest block of the page found in the rebuild. None where the page
    has no such block to place it by."""
    pw, ph = src_page.rect.width, src_page.rect.height
    region = fitz.Rect(box[0] * pw, box[1] * ph, box[2] * pw, box[3] * ph)
    anchors = [b for b in blocks if b.get("mismatch") is not None and b["mismatch"] <= 2 * LIMIT]
    if not anchors or region.is_empty:
        return None

    def off(b: Dict) -> float:
        r = fitz.Rect(b["src"])
        dx = max(r.x0 - region.x1, region.x0 - r.x1, 0.0)
        dy = max(r.y0 - region.y1, region.y0 - r.y1, 0.0)
        return dx + dy

    anchor = min(anchors, key=off)
    return _laid_over(fitz, src_path, out_path, anchor["page"], region, fitz.Rect(anchor["src"]), fitz.Rect(anchor["out"]))


def walk(result: Dict) -> List[Dict]:
    """Every node of the document the service gave, containers and blocks,
    in its order - each with the titles of the containers it stands in."""
    out: List[Dict] = []

    def down(node: Dict, depth: int) -> None:
        out.append({**node, "depth": depth})
        for child in node.get("children") or []:
            down(child, depth + 1)

    for root in result.get("containers") or []:
        down(root, 0)
    return out


def _alike(a: str, b: str) -> bool:
    a, b = _letters(a), _letters(b)
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= TITLE_LIKENESS


def headings_report(nodes: List[Dict]) -> Dict[str, Any]:
    """The book's contents against the document's headings."""
    heads = [n for n in nodes if n.get("type") == "ContainerUnit" and n.get("title")
             and n.get("semantic_type") not in ("document", "toc", "example")]
    toc = [n for n in nodes if n.get("type") == "TocEntryBlock" and (n.get("text") or "").strip()]
    answered = [e for e in toc if any(_alike(e["text"], h["title"]) for h in heads)]
    return {
        "headings": len(heads),
        "by_level": {str(l): sum(1 for h in heads if h.get("level") == l) for l in sorted({h.get("level") for h in heads})},
        "toc_entries": len(toc),
        "toc_linked": sum(1 for e in toc if e.get("anchor_id")),
        "toc_with_page": sum(1 for e in toc if e.get("target_page") is not None),
        "toc_answered_by_a_heading": len(answered),
        "toc_unanswered": [e["text"][:60] for e in toc if e not in answered][:40],
    }


def sheet(src_path: Path, out_path: Path, page_index: int, out_pages: List[int], path: Path) -> None:
    """A source page beside the pages it came out as."""
    def image(pdf: Path, index: int) -> Image.Image:
        pix = fitz.open(pdf)[index].get_pixmap(matrix=fitz.Matrix(SHEET_ZOOM, SHEET_ZOOM))
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    images = [image(src_path, page_index)] + [image(out_path, j) for j in out_pages[:3]]
    canvas = Image.new("RGB", (sum(i.width for i in images) + 12 * len(images), max(i.height for i in images)), "white")
    x = 0
    for im in images:
        canvas.paste(im, (x, 0))
        x += im.width + 12
    canvas.save(path)


def _stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": round(statistics.median(values), 4),
            "within_limit": round(sum(v <= LIMIT for v in values) / len(values), 4),
            "worst": round(max(values), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--rebuilt", required=True, type=Path)
    ap.add_argument("--result", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    src, out = fitz.open(args.source), fitz.open(args.rebuilt)
    nodes = walk(json.loads(args.result.read_text()))
    pages = map_pages(src, out)

    by_page: Dict[int, List[Dict]] = {}
    for n in nodes:
        if n.get("page_index") is not None:
            by_page.setdefault(n["page_index"], []).append(n)

    report_pages = []
    figures, tables = [], []
    for i, src_page in enumerate(src):
        out_pages = pages[i]
        blocks = block_overlays(args.source, args.rebuilt, src_page, i, out, out_pages) if out_pages else []
        measured = [b["mismatch"] for b in blocks if b.get("mismatch") is not None]
        entry = {
            "page": i,
            "rebuilt_pages": out_pages,
            "text": text_recall(src_page, [out[j] for j in out_pages]),
            "blocks": len(blocks),
            "blocks_found": sum(1 for b in blocks if b["found"]),
            "blocks_within_limit": sum(1 for m in measured if m <= LIMIT),
            "block_median": round(statistics.median(measured), 4) if measured else None,
            "kinds": {},
        }
        for n in by_page.get(i, []):
            entry["kinds"][n["type"]] = entry["kinds"].get(n["type"], 0) + 1
            box = n.get("bbox") or ((n.get("metadata") or {}).get("printed_ink") or {}).get("box")
            if n["type"] in ("DiagramBlock", "FigureBlock", "TableBlock") and box and out_pages:
                miss = region_overlay(args.source, args.rebuilt, i, src_page, list(box), blocks)
                (tables if n["type"] == "TableBlock" else figures).append(
                    {"page": i, "box": [round(v, 3) for v in box], "mismatch": miss})
        report_pages.append(entry)
        print(f"page {i:4d} -> {out_pages} text {entry['text']} blocks {entry['blocks_found']}/{entry['blocks']} "
              f"median {entry['block_median']} {entry['kinds']}", flush=True)

    texts = [p["text"] for p in report_pages if p["text"] is not None]
    kinds: Dict[str, int] = {}
    for n in nodes:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    summary = {
        "source_pages": len(src),
        "rebuilt_pages": len(out),
        "pages_lost": [p["page"] for p in report_pages if not p["rebuilt_pages"]],
        "pages_run_over": [p["page"] for p in report_pages if len(p["rebuilt_pages"]) > 1],
        "text": {"pages": len(texts), "median": round(statistics.median(texts), 4) if texts else None,
                 "pages_under_90": sorted(p["page"] for p in report_pages if p["text"] is not None and p["text"] < 0.9)},
        "blocks": {
            "total": sum(p["blocks"] for p in report_pages),
            "found": sum(p["blocks_found"] for p in report_pages),
            "within_limit": sum(p["blocks_within_limit"] for p in report_pages),
        },
        "figures": {**_stats([f["mismatch"] for f in figures if f["mismatch"] is not None]),
                    "found": len(figures), "not_placed": sum(1 for f in figures if f["mismatch"] is None)},
        "tables": {**_stats([t["mismatch"] for t in tables if t["mismatch"] is not None]),
                   "found": len(tables), "not_placed": sum(1 for t in tables if t["mismatch"] is None)},
        "headings": headings_report(nodes),
        "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
    }
    (args.out / "report.json").write_text(json.dumps(
        {"summary": summary, "pages": report_pages, "figures": figures, "tables": tables}, ensure_ascii=False, indent=1))

    # sheets to look at: the worst by text and by blocks, and every nth page
    by_text = sorted((p for p in report_pages if p["text"] is not None), key=lambda p: p["text"])[:SHEETS_WORST]
    by_blocks = sorted((p for p in report_pages if p["blocks"]),
                       key=lambda p: p["blocks_within_limit"] / p["blocks"])[:SHEETS_WORST]
    chosen = {p["page"]: "text" for p in by_text}
    chosen.update({p["page"]: "blocks" for p in by_blocks if p["page"] not in chosen})
    for i in range(0, len(src), SHEET_EVERY):
        chosen.setdefault(i, "nth")
    (args.out / "sheets").mkdir(exist_ok=True)
    for i, why in sorted(chosen.items()):
        if pages[i]:
            sheet(args.source, args.rebuilt, i, pages[i], args.out / "sheets" / f"{i:04d}_{why}.png")

    lines = [f"# {args.source.name}", "", "```json", json.dumps(summary, ensure_ascii=False, indent=1), "```"]
    (args.out / "report.md").write_text("\n".join(lines))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
