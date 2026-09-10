"""Confidence calibration and its wiring into the pipeline (RFC 0017 §3, §4)."""

import pytest

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.pipeline import PipelineRunner
from src.calibration.engine import (
    ConfidenceAction,
    ConfidenceCalibrator,
    confidence_action,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock


def test_category_rescaling_matches_rfc() -> None:
    calibrator = ConfidenceCalibrator()

    assert calibrator.calibrate_score(0.99, "tikz_vectorization") == pytest.approx(
        0.99 * 0.88 + 0.05
    )
    assert calibrator.calibrate_score(0.90, "ocr_extraction") == pytest.approx(0.855)


def test_unknown_category_passes_through() -> None:
    assert ConfidenceCalibrator().calibrate_score(0.77, "who_knows") == 0.77


def test_isotonic_fit_maps_overconfidence_to_observed_accuracy() -> None:
    """A model claiming 0.9 while being right half the time gets pulled down."""
    calibrator = ConfidenceCalibrator()
    predictions = [0.9] * 10 + [0.95] * 10
    truth = [True] * 5 + [False] * 5 + [True] * 5 + [False] * 5

    calibrator.fit("tikz_vectorization", predictions, truth)

    assert calibrator.calibrate_score(0.9, "tikz_vectorization") == pytest.approx(0.5)


def test_isotonic_curve_is_monotonic() -> None:
    calibrator = ConfidenceCalibrator()
    predictions = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    truth = [False, True, False, False, True, True, False, True, True]

    curve = calibrator.fit("ocr_extraction", predictions, truth)

    fitted = [y for _, y in curve]
    assert fitted == sorted(fitted)


def test_operational_thresholds() -> None:
    assert confidence_action(0.91) is ConfidenceAction.AUTO_COMMIT
    assert confidence_action(0.85) is ConfidenceAction.AUTO_COMMIT
    assert confidence_action(0.72) is ConfidenceAction.HITL_REVIEW
    assert confidence_action(0.60) is ConfidenceAction.HITL_REVIEW
    assert confidence_action(0.42) is ConfidenceAction.RETRY_FALLBACK


class _CalibratedAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="StubOCR",
                version="1.0.0",
                description="stub",
                krm_permissions={KRMPermission.READ},
                calibration_category="ocr_extraction",
            )
        )

    def run(self, doc, rg, kg, context=None) -> None:
        return None


class _PlainAnalyzer(_CalibratedAnalyzer):
    def __init__(self) -> None:
        BaseAnalyzer.__init__(
            self,
            AnalyzerManifest(
                name="StubPlain",
                version="1.0.0",
                description="stub",
                krm_permissions={KRMPermission.READ},
            ),
        )


def _doc() -> KnowledgeDocument:
    paragraph = ParagraphBlock(confidence_score=0.90)
    return KnowledgeDocument(root_containers=[ContainerUnit(children=[paragraph])])


def _paragraph(doc: KnowledgeDocument) -> ParagraphBlock:
    return doc.root_containers[0].children[0]


def test_pipeline_calibrates_declared_categories() -> None:
    doc = _doc()

    PipelineRunner([_CalibratedAnalyzer()]).execute(doc, ReadingGraph(), KnowledgeGraph())

    paragraph = _paragraph(doc)
    assert paragraph.confidence_score == pytest.approx(0.855)
    assert paragraph.metadata["calibration"]["raw_confidence"] == pytest.approx(0.90)


def test_analyzer_without_category_leaves_scores_untouched() -> None:
    doc = _doc()

    PipelineRunner([_PlainAnalyzer()]).execute(doc, ReadingGraph(), KnowledgeGraph())

    assert _paragraph(doc).confidence_score == pytest.approx(0.90)
    assert "calibration" not in (_paragraph(doc).metadata or {})


def test_a_node_is_calibrated_only_once() -> None:
    """Two calibrated analyzers in one run must not rescale the same score twice."""
    doc = _doc()

    PipelineRunner([_CalibratedAnalyzer(), _CalibratedAnalyzer()]).execute(
        doc, ReadingGraph(), KnowledgeGraph()
    )

    assert _paragraph(doc).confidence_score == pytest.approx(0.855)
