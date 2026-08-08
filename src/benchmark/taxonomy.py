"""
Error Taxonomy & Diagnostics for Knowledge Assembly Engine (KAE).

Implements ErrorCategory, TaxonomyErrorItem, QualityTaxonomyReport, and TaxonomyAnalyzer
according to RFC 0015.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List


class ErrorCategory(Enum):
    """
    Hierarchical error classification categories for document layout, text, tables, and graph.
    """
    TEXT_OCR_MISREAD = "TEXT_OCR_MISREAD"
    TEXT_ENCODING_BROKEN = "TEXT_ENCODING_BROKEN"
    TEXT_HYPHENATION_FAILED = "TEXT_HYPHENATION_FAILED"
    LAYOUT_COLUMN_ORDER_SWAPPED = "LAYOUT_COLUMN_ORDER_SWAPPED"
    LAYOUT_HEADER_MISCLASSIFIED = "LAYOUT_HEADER_MISCLASSIFIED"
    LAYOUT_SIDEBAR_LEAK = "LAYOUT_SIDEBAR_LEAK"
    TABLE_CELL_MERGE_MISSING = "TABLE_CELL_MERGE_MISSING"
    TABLE_ROW_SPLIT_FALSE = "TABLE_ROW_SPLIT_FALSE"
    GRAPH_MISSING_CAPTION = "GRAPH_MISSING_CAPTION"
    GRAPH_BROKEN_CROSSREF = "GRAPH_BROKEN_CROSSREF"
    SEMANTIC_WRONG_ENTITY = "SEMANTIC_WRONG_ENTITY"


@dataclass
class TaxonomyErrorItem:
    """
    Diagnostic error item representing a single extraction issue or anomaly.
    """
    category: ErrorCategory
    target_id: str
    description: str
    severity: str = "warning"


@dataclass
class QualityTaxonomyReport:
    """
    Aggregated quality and diagnostics taxonomy report across extraction runs.
    """
    total_errors_count: int
    errors_by_category: Dict[str, int]
    critical_blockers_count: int
    items: List[TaxonomyErrorItem] = field(default_factory=list)


class TaxonomyAnalyzer:
    """
    Analyzer for recording diagnostic extraction errors and compiling taxonomy reports.
    """

    def __init__(self) -> None:
        self._items: List[TaxonomyErrorItem] = []

    def add_error(
        self,
        category: ErrorCategory,
        target_id: str,
        description: str,
        severity: str = "warning",
    ) -> TaxonomyErrorItem:
        """
        Records a diagnostic error item.
        """
        item = TaxonomyErrorItem(
            category=category,
            target_id=target_id,
            description=description,
            severity=severity,
        )
        self._items.append(item)
        return item

    def generate_report(self) -> QualityTaxonomyReport:
        """
        Generates an aggregated QualityTaxonomyReport.
        """
        total_count = len(self._items)
        errors_by_cat: Dict[str, int] = {}
        critical_blockers = 0

        for item in self._items:
            cat_key = item.category.value
            errors_by_cat[cat_key] = errors_by_cat.get(cat_key, 0) + 1

            if item.severity.lower() in ("critical", "blocker"):
                critical_blockers += 1

        return QualityTaxonomyReport(
            total_errors_count=total_count,
            errors_by_category=errors_by_cat,
            critical_blockers_count=critical_blockers,
            items=list(self._items),
        )
