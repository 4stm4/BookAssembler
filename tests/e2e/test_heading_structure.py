"""E2E: the headings the real pipeline reads off scanned book pages - which
lines of a page are headings, in what order, and how they rank against
one another.

Each fixture is one page cut out of a scanned technical book (MCS-40
User's Manual, Zaks "Programming the Z80", Intel Series 3000 Reference
Manual). Its headings were read off the printed page by eye: their text,
and their rank on the page - 1 its highest, a larger rank a heading under
it, equal ranks headings of one level. A running head, a page number, a
figure's caption, a diagram's labels are no headings.

The page goes through the whole pipeline (PdfSourceAdapter, every
analyzer), and its headings are the titled containers under the
document's root, in the document's order. The test asks that they are
the expected ones - no heading missed, none made of a line that is not
one - in the expected order, and that their levels rank as printed: a
heading of a lower rank at a lower level, of an equal rank at the same
level. The levels themselves are the document's to number; one page
says only how they stand to each other.

A heading's text is matched loosely (difflib, _TITLE_LIKENESS): OCR's
reading of a scan misses a letter now and then, and that is no fault of
the heading's detection.
"""

import difflib
import re
from pathlib import Path

import pytest

from src.krm.models import ContainerUnit, KnowledgeDocument

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "heading"

# (title, rank) in reading order, as printed.
EXPECTED = {
    "mcs40_vii.pdf": [
        ("SUPPLEMENTAL DEVICES", 3),
        ("4702 - Erasable and Electrically Reprogrammable ROM", 4),
        ("4316 - Mask Programmable ROM", 4),
        ("4101 RAM", 4),
        ("3216/3226 - 4 bit Bidirectional Bus", 4),
        ("THE FUNCTIONS OF A COMPUTER", 1),
        ("A Typical Computer System", 2),
        ("The Architecture of a CPU", 2),
        ("ACCUMULATOR:", 3),
        ("PROGRAM COUNTER (JUMPS, SUBROUTINES AND THE STACK):", 3),
    ],
    "mcs40_ix.pdf": [
        ("ARITHMETIC/LOGIC UNIT (ALU):", 2),
        ("CONTROL CIRCUITRY:", 2),
        ("COMPUTER OPERATIONS", 1),
        ("TIMING:", 2),
        ("INSTRUCTION FETCH:", 2),
        ("MEMORY READ:", 2),
        ("MEMORY WRITE:", 2),
        ("INPUT/OUTPUT:", 2),
    ],
    "zaks_41.pdf": [
        ("EXTERNAL REPRESENTATION OF INFORMATION", 1),
        ("1. Binary", 2),
        ("2. Octal and Hexadecimal", 2),
    ],
    "zaks_46.pdf": [
        ("Z80 HARDWARE ORGANIZATION", 1),
        ("INTRODUCTION", 2),
        ("SYSTEM ARCHITECTURE", 2),
    ],
    "zaks_66.pdf": [
        ("INSTRUCTION FORMATS", 1),
        ("A One-Word Instruction", 2),
    ],
    "intel3000_2-17.pdf": [
        ("LOGICAL DESCRIPTION", 1),
        ("MICRO-FUNCTION BUS AND DECODER", 2),
        ("M-BUS AND I-BUS INPUTS", 2),
        ("SCRATCHPAD", 2),
        ("ACCUMULATOR AND D-BUS", 2),
        ("A AND B MULTIPLEXERS", 2),
        ("ALS AND K-BUS", 2),
        ("MEMORY ADDRESS REGISTER AND A-BUS", 2),
    ],
}

# How alike a heading's text and the expected title must read
# (difflib's ratio over their letters and figures, case aside): OCR misses
# a letter of a scan now and then. A chapter's number set over its title
# ("2" over "Z80 HARDWARE ORGANIZATION") may lead it.
_TITLE_LIKENESS = 0.85


def _extract(pdf_path: Path) -> KnowledgeDocument:
    """The document the real pipeline reads off a PDF, every analyzer run."""
    from src.adapters.pdf_adapter import PdfSourceAdapter
    from src.analyzers import create_default_pipeline
    from src.analyzers.pipeline import PipelineRunner
    from src.graph.knowledge_graph import KnowledgeGraph
    from src.graph.reading_graph import ReadingGraph

    with open(pdf_path, "rb") as fh:
        doc = PdfSourceAdapter().parse(fh, f"file://{pdf_path}")
    PipelineRunner(create_default_pipeline()).execute(doc, ReadingGraph(), KnowledgeGraph())
    return doc


def _headings(doc: KnowledgeDocument) -> list:
    """The document's headings: its titled containers under its root - not
    the root, which stands for the document - as (title, level), in the
    document's order. A caption's example container is none."""
    out = []

    def walk(node, depth):
        if not isinstance(node, ContainerUnit) or node.is_tombstoned:
            return
        if depth > 0 and node.title and node.semantic_type not in ("example", "toc"):
            out.append((node.title, node.level))
        for child in node.children:
            walk(child, depth + 1)

    for root in doc.root_containers:
        walk(root, 0)
    return out


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _alike(found: str, expected: str) -> bool:
    a, b = _letters(found), _letters(expected)
    if a.endswith(b) and len(a) - len(b) <= 3:
        return True  # a chapter's number leading its title
    return difflib.SequenceMatcher(None, a, b).ratio() >= _TITLE_LIKENESS


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_headings_match_the_printed_page(fixture):
    """The page's headings, in order, with their levels ranked as printed."""
    doc = _extract(FIXTURES / fixture)
    found = _headings(doc)
    expected = EXPECTED[fixture]

    # each expected heading found, in order; nothing else taken for one -
    # each found heading paired with the next expected one it reads as
    pairs = []
    k = 0
    for i, (title, _) in enumerate(found):
        j = next((j for j in range(k, len(expected)) if _alike(title, expected[j][0])), None)
        if j is not None:
            pairs.append((i, j))
            k = j + 1
    missed = [expected[j][0] for j in range(len(expected)) if j not in {p[1] for p in pairs}]
    extra = [found[i][0] for i in range(len(found)) if i not in {p[0] for p in pairs}]
    assert not missed and not extra, (
        f"{fixture}: headings missed {missed}; lines taken for headings that are none {extra}; "
        f"found {[t for t, _ in found]}"
    )

    # levels ranked as printed
    wrong = []
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            (ia, ka), (ib, kb) = pairs[a], pairs[b]
            ra, rb = expected[ka][1], expected[kb][1]
            la, lb = found[ia][1], found[ib][1]
            if (ra < rb) != (la < lb) or (ra == rb) != (la == lb):
                wrong.append(f"{expected[ka][0]!r} (rank {ra}, level {la}) vs {expected[kb][0]!r} (rank {rb}, level {lb})")
    assert not wrong, f"{fixture}: levels do not rank as printed: " + "; ".join(wrong[:8])
