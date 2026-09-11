"""ScanNoiseAnalyzer — scan debris is tombstoned, real text of any shape is not.

The check used to live in the PDF adapter and dropped blocks outright. On
the test books it discarded every dotted-leader contents line and every
Cyrillic paragraph without a Latin word; these tests pin both directions.
"""

import pytest

from src.analyzers import create_default_pipeline
from src.analyzers.scan_noise import ScanNoiseAnalyzer, is_scan_noise
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


@pytest.mark.parametrize("text", [
    ", 1IIIIiK,8I ,..i!C\"'-",          # the crest the check was written for
    "~!|;:' ,.,; il! I1l ;;",
    "}{ ~~ ^^ xqz ;; ~~",
])
def test_debris_is_noise(text):
    assert is_scan_noise(text)


@pytest.mark.parametrize("text", [
    # contents lines — dense, spaced and LaTeX-spaced leaders
    "2.1 Mandatory packages ................................ 3",
    "Emulator Architecture. . . . . .. ... . .. . . . .. . .. ..  10",
    "1.1  TEX Live и TEX Collection   .  .  .  .  .  .  .  .    2",
    "INTRODUCTION ........................ 1-1",
    "INDEX � 617",
    # Cyrillic with no Latin word at all
    "Содержание",
    "Базовые команды для рисования",
    "РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ",
    # numbers and codes are content, not letter debris
    "2048  128-256",
    "UM008011-0816",
    "03/09/2003 1:35 PM Page 1",
    "$5.00",
    # a broken font encoding is damaged text, not a smudge: never judged
    "Íå î÷åíü êðàòêîå ââåäåíèå",
    # instruction mnemonics have no real word and clean tokens (Zilog Z80
    # contents: seven entries were lost to the first version of the rule)
    "LD r, r' . . . . . . . . . . . . . . . . . . 71",
    "LD r,n . . . . . . . . . . . . . . . . . . . 72",
    "LD r, (IX+d) . . . . . . . . . . . . . . . . 75",
    "SBC HL, ss",
    "EX AF, AF′",
    "JP (IX)",
])
def test_real_text_is_not_noise(text):
    assert not is_scan_noise(text)


def _para(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
            page_or_screen_index=0,
        ),
    )


def test_analyzer_tombstones_noise_with_a_reason_and_keeps_text():
    noise, toc, ru = (_para(", 1IIIIiK,8I ,..i!C\"'-"),
                      _para("2.1 Mandatory packages ........ 3"),
                      _para("Содержание"))
    root = ContainerUnit(title="root", level=1, children=[noise, toc, ru])
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            root_containers=[root])
    ScanNoiseAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    assert noise.is_tombstoned
    assert noise.metadata["tombstone_reason"] == "scan_noise"
    assert root.children == [noise, toc, ru], "tombstoned, never removed"
    assert not toc.is_tombstoned and not ru.is_tombstoned


def test_runs_before_anything_reads_text_as_structure():
    names = [a.manifest.name for a in create_default_pipeline()]
    at = names.index("ScanNoiseAnalyzer")
    assert names.index("NormalizationAnalyzer") < at
    for later in ("HeadingAnalyzer", "TitlePageAnalyzer", "TocAnalyzer"):
        assert at < names.index(later)
