"""Debug-only: the style every cell carries from its source span - family,
size, weight - tallied per fixture.

Run with python3 (argument A or B), not pytest.
"""
import sys
from collections import Counter
sys.path.insert(0, "/app")
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
tally = Counter()
for row in t.grid:
    for cell in row:
        st = cell.visual_layout.style if cell.visual_layout else None
        if st is not None:
            tally[(st.font_family, st.is_bold, st.is_italic, st.is_monospace)] += 1
for key, n in tally.most_common():
    print(n, key)
