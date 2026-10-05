"""Debug-only: compile a fixture's rebuilt table and print the LaTeX
errors from the log, with the lines around each.

python3 tests/e2e/_debug_compile_log.py <pdf>
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

from src.assembler.latex_builder import build_latex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import _extract_table

table = _extract_table(Path(sys.argv[1]))
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    subprocess.run(["xelatex", "-interaction=nonstopmode", "t.tex"], cwd=td, capture_output=True)
    log = Path(td, "t.log").read_text(errors="replace").splitlines()
    src = tex.splitlines()
    for i, line in enumerate(log):
        if line.startswith("!"):
            print("\n".join(log[i:i + 6]))
            for l in log[i:i + 8]:
                if l.startswith("l.") and l[2:].split(" ")[0].isdigit():
                    n = int(l[2:].split(" ")[0])
                    print("TeX line", n, ":", src[n - 1][:900] if n <= len(src) else "?")
            print("---")
