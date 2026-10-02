"""Debug-only: a fixture table's metadata.

python3 tests/e2e/_debug_table_md.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import _extract_table

for k, v in sorted((_extract_table(Path(sys.argv[1])).metadata or {}).items()):
    print(f"{k}: {v}")
