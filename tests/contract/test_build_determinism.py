"""RFC 0009 §5.2 / 0021 §5.3: nothing non-deterministic leaks into KRM or the build."""
import os

import pytest

from src.analyzers.llm_refinement import LLMRefinementAnalyzer
from src.assembler import latex_builder
from src.krm.models import (
    ContainerUnit,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _para(text: str, conf: float) -> ParagraphBlock:
    p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])])
    p.classification_confidence = conf
    p.extraction_confidence = conf
    return p


class TestNoWallClockInKRM:
    """A timestamp in KRM makes two runs of the same source differ byte-for-byte."""

    def test_refinement_marker_is_not_a_timestamp(self):
        blocks = [_para("low confidence text", 0.2)]
        container = ContainerUnit(title="ch", level=1, children=blocks)
        blocks[0].metadata = {"llm_refined": True}

        collected: list = []
        LLMRefinementAnalyzer()._collect_low_confidence(container, collected)
        assert collected == [], "block marked llm_refined must be skipped"

    def test_legacy_timestamp_marker_still_skips(self):
        """Documents persisted before the switch must stay idempotent."""
        blocks = [_para("low confidence text", 0.2)]
        container = ContainerUnit(title="ch", level=1, children=blocks)
        blocks[0].metadata = {"llm_refined_at": 1756600000.0}

        collected: list = []
        LLMRefinementAnalyzer()._collect_low_confidence(container, collected)
        assert collected == []

    def test_unrefined_block_is_collected(self):
        blocks = [_para("low confidence text", 0.2)]
        container = ContainerUnit(title="ch", level=1, children=blocks)

        collected: list = []
        LLMRefinementAnalyzer()._collect_low_confidence(container, collected)
        assert len(collected) == 1


class TestSourceDateEpoch:
    def test_compile_pins_source_date_epoch(self, monkeypatch, tmp_path):
        seen: dict = {}

        class _Proc:
            stdout = b""

        def fake_run(cmd, **kw):
            seen.update(kw.get("env") or {})
            (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.5\n")
            return _Proc()

        monkeypatch.setattr(latex_builder.subprocess, "run", fake_run)
        tex = tmp_path / "doc.tex"
        tex.write_text("")

        latex_builder.compile_xelatex(str(tex), str(tmp_path))

        assert seen.get("SOURCE_DATE_EPOCH") == str(latex_builder.SOURCE_DATE_EPOCH)
        assert seen.get("FORCE_SOURCE_DATE") == "1"

    def test_epoch_is_constant_across_calls(self, monkeypatch, tmp_path):
        epochs: list = []

        class _Proc:
            stdout = b""

        def fake_run(cmd, **kw):
            epochs.append((kw.get("env") or {}).get("SOURCE_DATE_EPOCH"))
            (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.5\n")
            return _Proc()

        monkeypatch.setattr(latex_builder.subprocess, "run", fake_run)
        tex = tmp_path / "doc.tex"
        tex.write_text("")

        latex_builder.compile_xelatex(str(tex), str(tmp_path))
        latex_builder.compile_xelatex(str(tex), str(tmp_path))

        assert len(set(epochs)) == 1
