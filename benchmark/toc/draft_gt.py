"""Draft ground truth for a new bench book — for a human to check line by
line against the printed page, never to commit as is. Independent of the
analyzers: PyMuPDF words, a plain regex for the trailing page reference, and
a cross-check against the PDF outline.

  python3 -m benchmark.toc.draft_gt <book.pdf> <first> <last>

Pages are 1-based, inclusive. Rows run top to bottom across the whole page,
so a two-column contents page comes out interleaved: put it in reading
order by hand (left column, then right), as for mpman-ru and mcs40. A line
without a page is glued to the next one as a wrapped title; where it is a
description instead (zaks-z80), drop it.
"""
import difflib
import json
import re
import sys

import pymupdf

from benchmark.toc.bench import rows, section_key

PAGE = r"(?P<page>\d{1,4}(?:-\d{1,4})?|[ivxlcdm]{1,7})"
LINE = re.compile(r"^(?P<title>\S.*?)(?:\s|[.·…])+" + PAGE + r"$", re.I)


def main() -> None:
    path, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    entries = []
    with pymupdf.open(path) as pdf:
        for idx in range(first - 1, last):
            pending, prev_y1 = None, None
            for y0, x0, y1, text in rows(pdf[idx]):
                # A wrapped title continues on the very next row; a running
                # header is set apart from the first entry by a gap.
                if prev_y1 is not None and y0 - prev_y1 > (y1 - y0):
                    pending = None
                prev_y1 = y1
                m = LINE.match(text)
                if not m:
                    pending = f"{pending} {text}" if pending else text
                    continue
                title = m.group("title").strip()
                if pending:
                    title = pending[:-1] + title if pending.endswith("-") else f"{pending} {title}"
                    pending = None
                entries.append({"text": re.sub(r"\s+", " ", title), "page": m.group("page"),
                                "indent": round(x0, 1)})
        outline = pdf.get_toc()

    for e in entries:
        print(json.dumps(e, ensure_ascii=False))
    print(f"# {len(entries)} entries")
    if outline:
        a = [section_key(e["text"]) for e in entries]
        b = [section_key(t) for _, t, _ in outline]
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        print("# vs outline:", sum(x.size for x in sm.get_matching_blocks()),
              "matching of", len(a), "/", len(b))
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "equal":
                print("#", op, a[i1:i2][:6], "| outline:", b[j1:j2][:6])


if __name__ == "__main__":
    main()
