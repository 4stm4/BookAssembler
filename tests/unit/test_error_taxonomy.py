"""Error taxonomy tests (RFC 0015 §2, §3.3)."""

import pytest

from src.adapters.base import SourceAdapterParseError
from src.analyzers.base import SecurityViolationError
from src.benchmark.metrics import compute_cer, compute_wer
from src.benchmark.runner import RegressionError
from src.connectors.llm_base import LLMProviderUnavailableError
from src.errors import ErrorCategory, KAEError
from src.graph.reading_graph import CyclicReadingPathError
from src.plugins.loader import PluginLoadError
from src.plugins.mutations import MutationRejectedError
from src.plugins.sandbox import PluginExecutionError


@pytest.mark.parametrize(
    "error_cls,expected",
    [
        (SourceAdapterParseError, ErrorCategory.ANALYZER_PARSE_FAILURE),
        (SecurityViolationError, ErrorCategory.SECURITY_VIOLATION),
        (LLMProviderUnavailableError, ErrorCategory.LLM_TIMEOUT),
        (CyclicReadingPathError, ErrorCategory.ANALYZER_CONTRACT_VIOLATION),
        (PluginLoadError, ErrorCategory.PLUGIN_LOAD_FAILURE),
        (PluginExecutionError, ErrorCategory.PLUGIN_EXECUTION_FAILURE),
        (MutationRejectedError, ErrorCategory.SECURITY_VIOLATION),
        (RegressionError, ErrorCategory.QUALITY_REGRESSION),
    ],
)
def test_subsystem_errors_carry_a_category(error_cls, expected) -> None:
    error = error_cls("boom")

    assert isinstance(error, KAEError)
    assert error.category is expected
    assert str(error) == "boom"


def test_category_can_be_overridden_per_raise() -> None:
    error = LLMProviderUnavailableError(
        "429 from provider", category=ErrorCategory.LLM_RATE_LIMIT
    )

    assert error.category is ErrorCategory.LLM_RATE_LIMIT
    assert error.to_dict()["category"] == "LLM_RATE_LIMIT"


def test_context_reaches_the_audit_form() -> None:
    error = KAEError(
        "drift",
        category=ErrorCategory.DESYNC_TEXT_DRIFT,
        context={"node_id": "krm-42", "wer": 0.31},
    )

    assert error.to_dict() == {
        "category": "DESYNC_TEXT_DRIFT",
        "message": "drift",
        "context": {"node_id": "krm-42", "wer": 0.31},
    }


def test_cer_catches_drift_that_wer_misses() -> None:
    """Same word count, mangled characters: WER sees one substitution, CER sees the scale."""
    reference = "MOV R0, R1"
    hypothesis = "M0V R0, R1"

    assert compute_cer(reference, hypothesis) == pytest.approx(0.1)
    assert compute_cer(reference, reference) == 0.0
    assert compute_cer("", "") == 0.0
    assert compute_cer("", "spurious") == 1.0
    assert compute_wer(reference, hypothesis) > compute_cer(reference, hypothesis)
