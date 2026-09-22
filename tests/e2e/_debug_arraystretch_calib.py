"""Debug-only: calibrate the real relationship between \\arraystretch
and actual per-row height in compiled output, at the font size/leading
FIXTURE_A's own table uses (14.15pt/16.98pt), by compiling a few tiny
tables directly through the real compile_xelatex helper (not
reimplementing the pipeline - just isolating the one LaTeX mechanism
in question). Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import compile_xelatex

PREAMBLE = r"""
\documentclass[11pt]{book}
\usepackage{fontspec}
\usepackage{array}
\usepackage[a4paper,margin=2.2cm]{geometry}
\setmainfont{DejaVu Serif}
\newfontfamily\latinfont{TeX Gyre Termes}
\begin{document}
\begin{center}
\renewcommand{\arraystretch}{%s}
\fontsize{14.15}{16.98}\selectfont
\begin{tabular}{|c|}
\hline
\latinfont row1 \tabularnewline \hline
\latinfont row2 \tabularnewline \hline
\latinfont row3 \tabularnewline \hline
\latinfont row4 \tabularnewline \hline
\latinfont row5 \tabularnewline \hline
\end{tabular}
\end{center}
\end{document}
"""

for stretch in (0.6, 0.851, 1.0, 1.15):
    tex = PREAMBLE % stretch
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        d = fitz.open(pdf)
        p = d[0]
        ys = []
        for n in range(1, 6):
            r = p.search_for(f"row{n}")
            if r:
                ys.append(r[0].y0)
        d.close()
        deltas = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        print(f"stretch={stretch}: row y0s={[round(y,2) for y in ys]} deltas={[round(x,2) for x in deltas]}")
