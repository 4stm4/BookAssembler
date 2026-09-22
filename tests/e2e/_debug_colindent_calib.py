"""Debug-only: does a per-column indent actually work the way the fix
needs it to, and does it move the column RULES while doing so?

The defect being chased: LaTeX sets a column's text exactly \\tabcolsep
from its rule, but the source indents each column by its own amount
(measured on the decimal/binary fixture: 5.2-8.2pt on whichever side
each column is set against, against a tabcolsep of 1.57pt). A single
table-wide tabcolsep cannot express that, so the extra has to go into
the column spec per column.

Two mechanisms to check, rather than assume:
  left-set  : >{\\hspace{Xpt}}p{W}
  right-set : >{\\raggedleft}p{W}<{\\hspace{Xpt}}

What must hold for the fix to be usable: the text moves by X, and the
RULES do not (they are already landing within 0.6pt of the source and
must stay there).

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import compile_xelatex

_INK = 160

PREAMBLE = r"""
\documentclass[11pt]{book}
\usepackage{fontspec}
\usepackage{array}
\usepackage[a4paper,margin=2.2cm]{geometry}
\setmainfont{DejaVu Serif}
\newfontfamily\latinfont{TeX Gyre Termes}
\begin{document}
\begin{center}
\setlength{\tabcolsep}{1.57pt}
\fontsize{14.15}{16.98}\selectfont
%s
\end{center}
\end{document}
"""

_ROWS = (
    "\n"
    r"\hline \latinfont 00000000 & \latinfont 127 \tabularnewline \hline" "\n"
    r"\latinfont 00000001 & \latinfont 255 \tabularnewline \hline" "\n"
    r"\end{tabular}"
)

CASES = {
    "baseline (no indent)":
        r"\begin{tabular}{|p{2.83cm}|>{\raggedleft}p{2.57cm}|}" + _ROWS,
    # Measured: moves the left-set text by exactly what is asked, and
    # leaves the rules where they were. But \hspace only indents the
    # FIRST line of a wrapped cell, which the voltage-regulator
    # fixture's wide CONDITIONS column would expose, and the trailing
    # <{\hspace{}} did nothing at all for the right-set column - its
    # gap stayed 1.7pt whether the hspace was there or not.
    "hspace: left 6.3pt, right 6.6pt":
        r"\begin{tabular}{|>{\hspace{6.3pt}}p{2.83cm}|>{\raggedleft}p{2.57cm}<{\hspace{6.6pt}}|}" + _ROWS,
    # \leftskip / \rightskip are the paragraph-level equivalents: they
    # indent EVERY line of a p{} cell, and \raggedleft leaves the
    # stretch on the left, so setting \rightskip after it should pull a
    # right-set column's text off its right rule - the thing
    # <{\hspace{}} failed to do.
    "skips: leftskip 6.3pt, rightskip 6.6pt":
        r"\begin{tabular}{|>{\leftskip=6.3pt}p{2.83cm}|>{\raggedleft\rightskip=6.6pt}p{2.57cm}|}" + _ROWS,
}


def rules_and_text(pdf, anchor):
    d = fitz.open(pdf)
    p = d[0]
    hits = p.search_for(anchor)
    box = p.rect
    # Scan the strip the TABLE actually occupies, found from the anchor
    # itself. A hardcoded 5-25% band (tried first) missed this little
    # table entirely and returned no rules at all, which silently took
    # the right-set case's report down with it - the rule-stability
    # check is the whole point here, so it cannot depend on a guess
    # about where on the page the table landed.
    if hits:
        top = max(0.0, hits[0].y0 - 30)
        bot = min(box.height, hits[0].y1 + 30)
    else:
        top, bot = box.height * 0.05, box.height * 0.35
    pix = p.get_pixmap(clip=fitz.Rect(0, top, box.width, bot),
                       matrix=fitz.Matrix(4, 4))
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    ink = grey < _INK
    dens = ink.mean(axis=0)
    # 0.5 was too strict for a two-row test table: its vertical rules
    # cross only part of the scanned strip (which also spans the blank
    # margin above and below), so every rule fell under the threshold
    # and the scan reported none at all.
    cols = np.where(dens > 0.35)[0]
    rules = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 2:
                rules.append((start + prev) / 2.0 / 4.0)
                start = c
            prev = c
        rules.append((start + prev) / 2.0 / 4.0)
    hit = hits[0] if hits else None
    d.close()
    return rules, hit


for label, body in CASES.items():
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(PREAMBLE % body)
        pdf = compile_xelatex("t.tex", td)
        rules, hit = rules_and_text(pdf, "00000000")
        _, hit2 = rules_and_text(pdf, "127")
        print(f"--- {label}")
        print(f"    rules found: {len(rules)} -> {[round(r, 1) for r in rules]}")
        # Absolute positions ALWAYS, rule-relative gaps only when rules
        # were actually found. Reporting the right-set anchor only when
        # len(rules) >= 3 (the first version) meant a failed rule scan
        # silently deleted the one case this script exists to check.
        if hit:
            print(f"    '00000000' x0={hit.x0:7.1f}"
                  + (f"   gap from rule0 = {hit.x0 - rules[0]:5.1f}pt" if rules else ""))
        else:
            print("    '00000000' NOT FOUND")
        if hit2:
            print(f"    '127'      x1={hit2.x1:7.1f}"
                  + (f"   gap to rule2  = {rules[2] - hit2.x1:5.1f}pt" if len(rules) >= 3 else ""))
        else:
            print("    '127' NOT FOUND")
