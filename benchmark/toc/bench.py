"""TOC bench (RFC 0009): the printed table of contents of the books in
corpus.json, read by the pipeline, against a hand-checked ground truth.

Per book, all of:
  titles   number + title of every entry, in order, as printed;
  pages    the page reference each entry shows, as printed;
  targets  the page an entry points to carries that folio — or, for a page
           printed without one, its neighbours carry the folios around it;
  outline  for books with a meaningful PDF outline, target_page is the
           outline's page for the same section.
Folios and outline are read with PyMuPDF straight from the PDF, independent
of the analyzers under test. The books themselves are not in the repository
(see README.md); corpus.json pins each edition by sha256.

  python3 -m benchmark.toc.bench --books DIR [--out DIR] [book ...]

Exit status 0 only if every book is exact on all four.
"""
import argparse
import difflib
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
STOP_AFTER = "BlockClassifierAnalyzer"


def load_corpus() -> Dict[str, Dict[str, Any]]:
    with open(os.path.join(HERE, "corpus.json"), encoding="utf-8") as f:
        return json.load(f)


def load_gt(book: str) -> List[Dict[str, Any]]:
    with open(os.path.join(HERE, "gt", f"{book}.json"), encoding="utf-8") as f:
        return json.load(f)["entries"]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[\s.·…]+", " ", s)
    return s.strip().lower()


# ── the pipeline under test ─────────────────────────────────────────────────

def extract(pdf_path: str) -> Tuple[int, List[Dict[str, Any]]]:
    """Run the pipeline up to BlockClassifier; the TOC containers found and
    their live entries, in reading order."""
    from src.adapters.pdf_adapter import PdfSourceAdapter
    from src.analyzers import create_default_pipeline
    from src.analyzers.pipeline import PipelineRunner
    from src.graph.knowledge_graph import KnowledgeGraph
    from src.graph.reading_graph import ReadingGraph
    from src.krm.models import ContainerUnit, TocEntryBlock

    chain = []
    for a in create_default_pipeline():
        chain.append(a)
        if a.manifest.name == STOP_AFTER:
            break
    with open(pdf_path, "rb") as f:
        doc = PdfSourceAdapter().parse(f, f"test://{os.path.basename(pdf_path)}")
    PipelineRunner(chain).execute(doc, ReadingGraph(), KnowledgeGraph())

    tocs, entries = [0], []

    def walk(n: Any) -> None:
        if isinstance(n, ContainerUnit):
            if n.semantic_type == "toc":
                tocs[0] += 1
            for c in n.children:
                walk(c)
        elif isinstance(n, TocEntryBlock) and not n.is_tombstoned:
            vl = n.visual_layout
            entries.append({
                # The printed line is number + title; compare it whole.
                "text": f"{n.chapter_number or ''} {n.entry_text}".strip(),
                "chapter": n.chapter_number,
                "page_label": n.page_label,
                "level": n.level,
                "target_page": n.target_page,
                "anchored": bool(n.anchor_id),
                "src_page": vl.page_or_screen_index if vl else None,
                "description": (n.metadata or {}).get("toc_description"),
            })

    for c in doc.root_containers:
        walk(c)
    return tocs[0], entries


def shown_page(e: Dict[str, Any]) -> Optional[str]:
    """The page reference an entry shows the reader."""
    if e.get("page_label"):
        return e["page_label"]
    return str(e["target_page"] + 1) if isinstance(e.get("target_page"), int) else None


# ── the book itself, read independently ─────────────────────────────────────

def rows(page: Any) -> List[Tuple[float, float, float, str]]:
    """The visual rows of a page, top to bottom: words whose vertical centres
    lie within half a word height of each other, joined left to right.
    Each row is (y0, x0, y1, text). Coordinates are as the page is shown: a
    landscape page stored rotated (sbc6120, pages 53-55) has its folio at the
    shown bottom edge, not at the edge of the unrotated content."""
    m = page.rotation_matrix
    words = []
    for w in page.get_text("words"):
        r = pymupdf.Rect(w[:4]) * m
        words.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    groups: List[List[Any]] = []
    for w in words:
        if groups:
            head = groups[-1][0]
            if abs((w[1] + w[3]) / 2 - (head[1] + head[3]) / 2) <= max(head[3] - head[1], 1.0) / 2:
                groups[-1].append(w)
                continue
        groups.append([w])
    out = []
    for g in groups:
        g.sort(key=lambda w: w[0])
        out.append((min(w[1] for w in g), g[0][0], max(w[3] for w in g), " ".join(w[4] for w in g)))
    return out


class Folios:
    """Tokens printed at the top and bottom edges of each page — where a
    folio sits. A folio printed as 2·15 reads as 2-15."""

    EDGE_ROWS = 4

    def __init__(self, pdf: Any) -> None:
        self._pdf = pdf
        self._cache: Dict[int, Set[str]] = {}

    def on(self, idx: int) -> Set[str]:
        if not 0 <= idx < self._pdf.page_count:
            return set()
        if idx not in self._cache:
            rs = [r[3] for r in rows(self._pdf[idx])]
            edge = " ".join(rs[:self.EDGE_ROWS] + rs[-self.EDGE_ROWS:])
            edge = re.sub(r"(\d)\s*[·‧]\s*(\d)", r"\1-\2", edge)
            self._cache[idx] = {t.strip(".,;:'’`·") for t in edge.split()}
        return self._cache[idx]


def _shifted(label: Optional[str], d: int) -> Optional[str]:
    m = re.match(r"^(\d+)-(\d+)$", label or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)) + d}"
    return str(int(label) + d) if (label or "").isdigit() else None


_SECTION_NUMBER = re.compile(
    r"^\s*(?:(?:chapter|appendix|part|глава|приложение)\s+)?"
    r"(?:[\dA-Z]{1,3}(?:\.\d+)*\.?|[ivxl]+\.?)\s+")


def section_key(title: str) -> str:
    """A title without its section number: outlines usually carry none."""
    s = _SECTION_NUMBER.sub("", unicodedata.normalize("NFKC", title or "").lower())
    return re.sub(r"[\W_]+", " ", s).strip()


# ── one book ────────────────────────────────────────────────────────────────

@dataclass
class BookResult:
    book: str
    edition_ok: bool = True
    tocs: int = 0
    gt: int = 0
    got: int = 0
    titles: int = 0
    pages: int = 0
    on_page: int = 0
    by_neighbours: int = 0
    outline_right: Optional[int] = None
    secs: float = 0.0
    diffs: List[Tuple[str, List[str], List[str]]] = field(default_factory=list)
    page_bad: List[Tuple[str, Optional[str], Optional[str]]] = field(default_factory=list)
    unconfirmed: List[Tuple[str, Optional[str], int]] = field(default_factory=list)
    missing: List[Tuple[str, Optional[str]]] = field(default_factory=list)
    outline_wrong: List[Tuple[str, Optional[str], int, int]] = field(default_factory=list)
    entries: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return (self.edition_ok
                and self.titles == self.gt == self.got == self.pages
                and not self.unconfirmed and not self.missing and not self.outline_wrong)

    def report(self) -> str:
        outline = "—" if self.outline_right is None else \
            f"right {self.outline_right}, wrong {len(self.outline_wrong)}"
        lines = [f"### {self.book}: tocs={self.tocs} gt={self.gt} got={self.got} "
                 f"titles={self.titles} pages={self.pages} | targets: on page {self.on_page}, "
                 f"by neighbours {self.by_neighbours}, unconfirmed {len(self.unconfirmed)}, "
                 f"missing {len(self.missing)} | outline: {outline} "
                 f"{'EXACT' if self.exact else ''} {self.secs}s"]
        if not self.edition_ok:
            lines.append("   EDITION: sha256 differs from corpus.json — not the book the ground truth is for")
        lines += [f"   {op:7s} gt={a[:4]} got={b[:4]}" for op, a, b in self.diffs[:25]]
        lines += [f"   page    {t!r}: gt={want} got={have}" for t, want, have in self.page_bad[:10]]
        lines += [f"   target  {t!r} ({lab}) -> page {tp}: folio not there" for t, lab, tp in self.unconfirmed[:10]]
        lines += [f"   target  {t!r} ({lab}): none" for t, lab in self.missing[:10]]
        lines += [f"   outline {t!r} ({lab}) -> page {tp}, outline says {want}"
                  for t, lab, tp, want in self.outline_wrong[:10]]
        return "\n".join(lines)


def _compare(r: BookResult, gt: List[Dict[str, Any]], got: List[Dict[str, Any]]) -> None:
    """Titles in order, then — for the matched ones — the printed page."""
    a = [norm(e["text"]) for e in gt]
    b = [norm(e["text"]) for e in got]
    r.gt, r.got = len(a), len(b)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            r.diffs.append((op, a[i1:i2], b[j1:j2]))
            continue
        r.titles += i2 - i1
        for i, j in zip(range(i1, i2), range(j1, j2)):
            if norm(gt[i].get("page")) == norm(shown_page(got[j])):
                r.pages += 1
            else:
                r.page_bad.append((gt[i]["text"], gt[i].get("page"), shown_page(got[j])))


def _check_targets(r: BookResult, pdf: Any, got: List[Dict[str, Any]]) -> None:
    folios = Folios(pdf)
    for e in got:
        tp, lab = e.get("target_page"), e.get("page_label")
        if not isinstance(tp, int):
            r.missing.append((e["text"][:40], lab))
        elif lab and lab in folios.on(tp):
            r.on_page += 1
        elif _shifted(lab, -1) in folios.on(tp - 1) or _shifted(lab, 1) in folios.on(tp + 1):
            r.by_neighbours += 1
        else:
            r.unconfirmed.append((e["text"][:40], lab, tp))


def _check_outline(r: BookResult, pdf: Any, got: List[Dict[str, Any]]) -> None:
    """Entries and outline aligned in order: a title can repeat across
    chapters (buildroot has several "Config.in file"), so a lookup by title
    would send a later entry to the first section of that name."""
    outline = [(section_key(title), page - 1) for _level, title, page in pdf.get_toc() if page >= 1]
    a = [section_key(e["text"]) for e in got]
    b = [key for key, _ in outline]
    r.outline_right = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            e, want = got[i], outline[j][1]
            if not isinstance(e.get("target_page"), int):
                continue
            if e["target_page"] == want:
                r.outline_right += 1
            else:
                r.outline_wrong.append((e["text"][:40], e.get("page_label"), e["target_page"], want))


def run_book(book: str, books_dir: str, corpus: Optional[Dict[str, Dict[str, Any]]] = None) -> BookResult:
    meta = (corpus or load_corpus())[book]
    path = os.path.join(books_dir, f"{book}.pdf")
    r = BookResult(book, edition_ok=sha256(path) == meta["sha256"])
    t = time.time()
    r.tocs, r.entries = extract(path)
    r.secs = round(time.time() - t, 1)
    _compare(r, load_gt(book), r.entries)
    with pymupdf.open(path) as pdf:
        _check_targets(r, pdf, r.entries)
        if meta.get("outline"):
            _check_outline(r, pdf, r.entries)
    return r


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="TOC bench: printed contents vs ground truth.")
    ap.add_argument("--books", required=True, help="directory holding <book>.pdf for each corpus book")
    ap.add_argument("--out", help="write each book's extracted entries to OUT/<book>.json")
    ap.add_argument("book", nargs="*", help="books to run (default: the whole corpus)")
    args = ap.parse_args(argv)
    logging.disable(logging.WARNING)

    corpus = load_corpus()
    books = args.book or sorted(corpus)
    unknown = [b for b in books if b not in corpus]
    if unknown:
        ap.error(f"not in corpus.json: {' '.join(unknown)}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    exact = []
    for book in books:
        try:
            r = run_book(book, args.books, corpus)
        except Exception as ex:  # a crash is a result too
            print(f"### {book}: CRASH {type(ex).__name__}: {ex}")
            continue
        print(r.report(), flush=True)
        if args.out:
            with open(os.path.join(args.out, f"{book}.json"), "w", encoding="utf-8") as f:
                json.dump({"tocs": r.tocs, "entries": r.entries}, f, ensure_ascii=False, indent=1)
        if r.exact:
            exact.append(book)
    print(f"\n=== EXACT {len(exact)}/{len(books)}: {' '.join(exact)}")
    return 0 if len(exact) == len(books) else 1


if __name__ == "__main__":
    sys.exit(main())
