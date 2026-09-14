"""KRM roundtrip: a real scanned page image -> OCR -> TableDetectorAnalyzer.

Fixture: tests/fixtures/decimal_binary_table.png, a screenshot of Fig. 1.2
"Decimal-Binary Table" (a two-column decimal/binary lookup table). The image
carries no text layer, so it is embedded as the sole content of a one-page
PDF (RFC 0008: a page with images and no extractable text is flagged
needs_ocr). PdfSourceAdapter never produces a TableBlock on its own - the
real path is:

    image -> PdfSourceAdapter (flags needs_ocr) -> OCRAnalyzer (real vision
    call, recovers ParagraphBlock lines from the picture) -> TableDetectorAnalyzer
    (clusters the aligned rows into a TableBlock)

The expected grid is the table as printed in the image, so this checks the
whole chain against what a human reading the picture would transcribe -
nothing dropped, reordered, or garbled (RFC 0001 SS2.4: no silent deletion).

Requires a reachable vision agent (configured host, e.g. the project's
ollama vision model) - this test does no network mocking and is meant to run
where that agent is reachable, not as an isolated unit test on a machine
with no agent configured.
"""

import io
import logging
import time
from pathlib import Path

import pytest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logging.getLogger("src.agents").setLevel(logging.DEBUG)
logging.getLogger("src.analyzers.ocr").setLevel(logging.DEBUG)

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.agents import pick
from src.analyzers.ocr import OCRAnalyzer
from src.analyzers.table import TableDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ParagraphBlock, TableBlock

FIXTURE_IMAGE = Path(__file__).parent.parent / "fixtures" / "decimal_binary_table.png"

# The table exactly as printed in the fixture image (Fig. 1.2), left column
# read top to bottom: decimal value, its 8-bit binary value.
EXPECTED_ROWS = [
    "0 00000000", "1 00000001", "2 00000010", "3 00000011", "4 00000100",
    "5 00000101", "6 00000110", "7 00000111", "8 00001000", "9 00001001",
    "10 00001010", "11 00001011", "12 00001100", "13 00001101", "14 00001110",
    "15 00001111", "16 00010000", "17 00010001", "31 00011111",
]


def _pdf_with_image(image_path: Path) -> bytes:
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(image_path))
    data = doc.tobytes()
    doc.close()
    return data


def _grid_row_texts(table: TableBlock):
    rows = []
    for row in table.grid:
        texts = []
        for cell in row:
            for block in cell.content:
                for inline in block.inlines:
                    for span in inline.spans:
                        texts.append(span.text)
        rows.append(" ".join(" ".join(texts).split()))
    return rows


@pytest.mark.skipif(not FIXTURE_IMAGE.exists(), reason="fixture image missing")
def test_roundtrip_table_block(tmp_path):
    """The real Fig. 1.2 screenshot must round-trip through OCR and
    TableDetectorAnalyzer into a TableBlock matching what is printed on it."""
    host, model, kind = pick("vision")
    print(f"[roundtrip] vision agent: host={host} model={model} kind={kind}", flush=True)
    if not host:
        pytest.skip("no reachable vision agent configured for OCR")

    pdf_path = tmp_path / "decimal_binary_table.pdf"
    pdf_path.write_bytes(_pdf_with_image(FIXTURE_IMAGE))
    print(f"[roundtrip] built PDF at {pdf_path} ({pdf_path.stat().st_size} bytes)", flush=True)

    doc = PdfSourceAdapter().parse(
        io.BytesIO(pdf_path.read_bytes()), f"file://{pdf_path}"
    )
    print(f"[roundtrip] parsed doc: {len(doc.root_containers[0].children)} top-level children", flush=True)

    rg, kg = ReadingGraph(), KnowledgeGraph()

    t0 = time.time()
    print("[roundtrip] calling OCRAnalyzer.run() ...", flush=True)
    OCRAnalyzer().run(doc, rg, kg)
    print(f"[roundtrip] OCRAnalyzer.run() returned after {time.time() - t0:.1f}s", flush=True)

    recovered = [c for c in doc.root_containers[0].children
                 if isinstance(c, ParagraphBlock) and not c.is_tombstoned]
    print(f"[roundtrip] {len(recovered)} live ParagraphBlock after OCR:", flush=True)
    for p in recovered[:40]:
        text = " ".join(s.text for i in (p.inlines or []) for s in i.spans)
        print(f"[roundtrip]   line: {text!r}", flush=True)

    TableDetectorAnalyzer().run(doc, rg, kg)
    print("[roundtrip] TableDetectorAnalyzer.run() done", flush=True)

    container = doc.root_containers[0]
    tables = [c for c in container.children if isinstance(c, TableBlock)]
    print(f"[roundtrip] {len(tables)} TableBlock found", flush=True)
    assert len(tables) == 1, f"expected exactly one TableBlock, got {len(tables)}"
    table = tables[0]

    actual_rows = _grid_row_texts(table)
    positions = []
    for expected_row in EXPECTED_ROWS:
        assert expected_row in actual_rows, (
            f"row {expected_row!r} from the image is missing in the "
            f"extracted table: {actual_rows}"
        )
        positions.append(actual_rows.index(expected_row))
    assert positions == sorted(positions), (
        "extracted rows must preserve the image's top-to-bottom order: "
        f"{actual_rows}"
    )

    absorbed = [c for c in container.children if isinstance(c, ParagraphBlock)]
    assert absorbed and all(p.is_tombstoned for p in absorbed if p in container.children), (
        "OCR-recovered rows merged into the table must be tombstoned, not "
        "deleted (RFC 0001 SS2.4)"
    )
