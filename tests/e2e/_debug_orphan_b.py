"""Debug-only: dump _merge_orphan_rows decisions for FIXTURE_B via
DEBUG_ORPHAN=1 env var instrumentation already in analyzer.py. Run with
python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table

_extract_table(FIXTURE_B)
