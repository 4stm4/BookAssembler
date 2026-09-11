"""HeadingAnalyzer — promotes large-font paragraphs into the container tree.

The case that matters here: a paragraph an earlier analyzer already
tombstoned (a repeating running header EphemeraDetector removed) can still
have a large font — headers usually do. Promoting it to a heading builds a
fresh, non-tombstoned ContainerUnit at the same id, resurrecting the node and
tripping the No Silent Deletions guard (RFC 0001 §2.4). This actually failed
a real pipeline run ("Parse error: Analyzer 'HeadingAnalyzer' un-tombstoned
node ...").
"""

import pytest

from src.analyzers.heading import HeadingAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, size: float = 12.0) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=None,
            style=StyleDescriptor(font_size_pt=size),
        ),
    )


def _run(children):
    root = ContainerUnit(title="root", level=1, children=children)
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            root_containers=[root])
    HeadingAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    return root


class TestTombstoneIsRespected:
    def test_a_tombstoned_large_font_block_is_not_promoted(self):
        """The bug: promoting it resurrects the node at the same id."""
        header = _para("Z80 CPU User Manual", size=20.0)
        header.is_tombstoned = True
        root = _run([
            header,
            _para("Body text explaining the instruction set.", size=12.0),
        ])
        assert all(
            not (isinstance(c, ContainerUnit) and c.id == header.id)
            for c in root.children
        ), "a tombstoned block was resurrected as a heading container"
        # It stays exactly as it was — untouched, still tombstoned.
        survivor = next(c for c in root.children if getattr(c, "id", None) == header.id)
        assert isinstance(survivor, ParagraphBlock)
        assert survivor.is_tombstoned

    def test_a_tombstoned_block_does_not_skew_the_threshold(self):
        """A repeating oversized header must not raise the body-size baseline
        and make real, smaller headings invisible."""
        huge_header = _para("RUNNING HEADER", size=40.0)
        huge_header.is_tombstoned = True
        root = _run([
            huge_header,
            _para("Chapter One", size=16.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert any(h.title == "Chapter One" for h in headings), (
            "a tombstoned outlier skewed the threshold past a real heading"
        )


class TestOcrGarbageIsNotPromoted:
    """A scanned page's diagram labels and code comments can be large-font
    and still contain an embedded real word — found on the Intel Series 3000
    manual (1976), where OCR noise like "MICRO-{;;O-i II" and "MAO.
    ~IIIIIIIII t t ," was promoted to fake L1 chapter headings alongside the
    real ones."""

    @pytest.mark.parametrize("garbage", [
        "MICRO-{;;O-i II",
        "IS' AC, lllI_~_~ACO",
        "-~l",
        "MAO. ~IIIIIIIII t t ,",
        "MIP I I: D",
        "~:Y",
    ])
    def test_symbol_heavy_noise_is_rejected(self, garbage):
        root = _run([
            _para(garbage, size=18.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert not any(h.title == garbage for h in headings)

    @pytest.mark.parametrize("real_heading", [
        "3216/3226 PARALLEL BIDIRECTIONAL BUS DRIVER",
        "APPENDIX C CENTRAL PROCESSOR SCHEMATICS",
        "SCHOTTKY BIPOLAR LSI MICROCOMPUTER SET",
    ])
    def test_real_headings_with_digits_and_punctuation_still_promote(self, real_heading):
        """The filter must not reject a real heading for containing numbers
        or an acronym-like run alongside its words."""
        root = _run([
            _para(real_heading, size=18.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert any(h.title == real_heading for h in headings)


class TestSyntacticNoiseIsNotPromoted:
    """The half of the garbage that word-ratio cannot reach: a real word
    embedded in a mangled source-code comment or a diagram/pinout label —
    both score in the same ratio range as a genuine heading. These carry
    their own syntactic tells instead. Also found on the Intel Series 3000
    manual."""

    @pytest.mark.parametrize("garbage", [
        "'* INITIALIZATION SEQUENCE",
        "1* RESTORE INTE.R~UI'T STRUCTURE *'",
        "VALUE-GROUP 1: GET (AC) IN AC *'",
        "/* LOAD DISPLACEMENT AND TEST fOR ZERO USING Z FLAG *'",
        "NOTE: ALTERNATIVE TEST LOAD _0 'R -< ~",
        "PIN SYMBOL NAME AND TYPE FUNCTION R=- = }--",
        "INTERRUPT STROBE ENABLE \" r----'",
    ])
    def test_mangled_comments_and_trailing_junk_are_rejected(self, garbage):
        root = _run([
            _para(garbage, size=18.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert not any(h.title == garbage for h in headings)

    @pytest.mark.parametrize("real_heading", [
        "3216/3226 PARALLEL BIDIRECTIONAL BUS DRIVER",
        "Central Processor Designs Using The Intel Series 3000",
        "APPENDIX C CENTRAL PROCESSOR SCHEMATICS",
    ])
    def test_real_headings_are_not_caught_by_the_noise_patterns(self, real_heading):
        root = _run([
            _para(real_heading, size=18.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert any(h.title == real_heading for h in headings)


class TestOrdinaryPromotion:
    def test_a_normal_large_font_block_still_becomes_a_heading(self):
        root = _run([
            _para("Introduction", size=18.0),
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        headings = [c for c in root.children if isinstance(c, ContainerUnit)]
        assert any(h.title == "Introduction" for h in headings)

    def test_promotion_preserves_the_source_id(self):
        """RFC 0001 §2.3: reclassification keeps identity."""
        block = _para("Introduction", size=18.0)
        root = _run([
            block,
            _para("Ordinary body text at normal size.", size=12.0),
            _para("More ordinary body text at normal size.", size=12.0),
        ])
        heading = next(c for c in root.children if isinstance(c, ContainerUnit))
        assert heading.id == block.id
