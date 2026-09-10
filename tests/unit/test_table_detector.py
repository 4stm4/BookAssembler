"""TableDetector must not tombstone blocks it does not absorb."""
class TestRejectedRunKeepsBlocks:
    """RFC 0001 §2.4: tombstoning is for content absorbed elsewhere.

    A run that fails validation has nothing to absorb it, so its blocks must
    stay alive — they were being marked before the checks ran and vanished.
    """

    def _doc(self, texts, y0=0.60, step=0.03):
        from src.krm.models import (
            ContainerUnit, KnowledgeDocument, NormalizedRect,
            ParagraphBlock, StyledTextSpan, TextLineInline, VisualLayout,
        )
        kids = []
        for i, t in enumerate(texts):
            y = y0 + i * step
            kids.append(ParagraphBlock(
                inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])],
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(0.09, y, 0.45, y + 0.02),
                    page_or_screen_index=1,
                ),
            ))
        c = ContainerUnit(title="ch", children=kids)
        return KnowledgeDocument(title="T", root_containers=[c]), c

    def _run(self, doc):
        from src.analyzers.table import TableDetectorAnalyzer
        from src.graph.knowledge_graph import KnowledgeGraph
        from src.graph.reading_graph import ReadingGraph
        TableDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    def test_appendix_list_survives(self):
        """The real case: four TOC appendix lines were silently deleted."""
        doc, c = self._doc([
            "Appendix A  Equipment", "Appendix B  Staff",
            "Appendix C  Costs", "Appendix D  Glossary",
        ])
        self._run(doc)
        alive = [ch for ch in c.children if not ch.is_tombstoned]
        assert len(alive) == 4, "rejected run tombstoned its blocks anyway"
        assert not any(type(ch).__name__ == "TableBlock" for ch in c.children)

    def test_no_block_is_tombstoned_without_a_table(self):
        doc, c = self._doc(["A  1", "B  2", "C  3", "D  4"])
        self._run(doc)
        tombstoned = [ch for ch in c.children if ch.is_tombstoned]
        tables = [ch for ch in c.children if type(ch).__name__ == "TableBlock"]
        assert not tombstoned or tables, "content tombstoned with nothing to absorb it"

    def test_real_table_still_detected(self):
        """The guard must not disarm detection of genuine tables."""
        doc, c = self._doc([
            "Year   Count   Total", "1979   12      144", "1980   15      225",
            "1981   18      324", "1982   21      441", "1983   24      576",
        ])
        self._run(doc)
        tables = [ch for ch in c.children if type(ch).__name__ == "TableBlock"]
        assert len(tables) == 1
        assert any(ch.is_tombstoned for ch in c.children)
