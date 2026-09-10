"""Error taxonomy for KAE subsystems (RFC 0015 §2).

Every failure the engine raises carries an actionable category, so an operator
reading the audit log or a job failure can tell a provider timeout from a broken
analyzer without parsing exception text.

Subsystem exceptions keep their own names and modules and inherit from KAEError,
so existing `except SourceAdapterParseError` sites keep working while
`except KAEError` now catches anything the engine raises deliberately.
"""

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    """
    Actionable error domains across KAE subsystems (RFC 0015 §2).
    """
    STORAGE_READ_FAILURE = "STORAGE_READ_FAILURE"
    STORAGE_WRITE_FAILURE = "STORAGE_WRITE_FAILURE"
    ANALYZER_OCR_FAIL = "ANALYZER_OCR_FAIL"
    ANALYZER_TIKZ_SYNTAX_ERROR = "ANALYZER_TIKZ_SYNTAX_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    LLM_HALLUCINATION_DETECTED = "LLM_HALLUCINATION_DETECTED"
    DESYNC_TEXT_DRIFT = "DESYNC_TEXT_DRIFT"
    LATEX_COMPILATION_ERROR = "LATEX_COMPILATION_ERROR"

    ANALYZER_PARSE_FAILURE = "ANALYZER_PARSE_FAILURE"
    ANALYZER_CONTRACT_VIOLATION = "ANALYZER_CONTRACT_VIOLATION"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    PLUGIN_LOAD_FAILURE = "PLUGIN_LOAD_FAILURE"
    PLUGIN_EXECUTION_FAILURE = "PLUGIN_EXECUTION_FAILURE"
    QUALITY_REGRESSION = "QUALITY_REGRESSION"


class KAEError(Exception):
    """Base for every error KAE raises deliberately, tagged with its category."""

    category: ErrorCategory = ErrorCategory.ANALYZER_CONTRACT_VIOLATION

    def __init__(
        self,
        message: str = "",
        category: Optional[ErrorCategory] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        if category is not None:
            self.category = category
        self.context: Dict[str, Any] = context or {}

    def to_dict(self) -> Dict[str, Any]:
        """Audit-log friendly form."""
        return {
            "category": self.category.value,
            "message": str(self),
            "context": self.context,
        }
