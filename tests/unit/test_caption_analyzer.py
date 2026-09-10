"""CaptionAnalyzer — reclassifies "Figure N: ..." paragraphs into CaptionBlock.

The case that matters here: a paragraph an earlier analyzer already tombstoned
(a running head EphemeraDetector removed, a row TableDetector absorbed) must
not be reclassified — a fresh CaptionBlock with the same id and no tombstone
resurrects the node and trips the No Silent Deletions guard (RFC 0001 §2.4).
This actually failed pipeline runs on the Zilog Z80 manual.
"""

import pytest

from src.analyzers.caption import CaptionAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    CaptionBlock,
    ContainerUnit,
    FigureBlock,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _para(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
    )


def _run(children):
    c = ContainerUnit(title="ch", children=children)
    doc = KnowledgeDocument(title="T", root_containers=[c])
    CaptionAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    return doc.root_containers[0].children


def test_caption_paragraph_becomes_a_caption_block():
    fig = FigureBlock()
    out = _run([fig, _para("Figure 1: The Z80 register set")])
    assert isinstance(out[1], CaptionBlock)
    assert out[1].label_number == "1"
    assert out[1].target_block_id == fig.id


def test_tombstoned_paragraph_is_left_alone():
    """The bug: reclassifying it here un-tombstones it."""
    ghost = _para("Figure 1: caption text that repeats as a running head")
    ghost.is_tombstoned = True
    out = _run([FigureBlock(), ghost])
    assert out[1] is ghost
    assert out[1].is_tombstoned
    assert not isinstance(out[1], CaptionBlock)


def test_non_caption_paragraphs_are_untouched():
    out = _run([_para("Just a sentence about timing.")])
    assert isinstance(out[0], ParagraphBlock)
    assert not isinstance(out[0], CaptionBlock)
