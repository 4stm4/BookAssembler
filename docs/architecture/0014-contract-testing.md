# RFC 0014: Contract Testing for Analyzers and Plugins

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0014 establishes the contract testing framework for KAE analyzers, custom CV extractors, and LLM plugins. Contract testing guarantees that third-party plugins and core extractors adhere strictly to KRM input/output schemas, schema validation invariants, and non-breaking type safety.

---

## 2. Contract Test Suite Requirements

Every analyzer module must implement the `KAEAnalyzerContract` interface:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class KAEAnalyzerContract(ABC):
    @abstractmethod
    def validate_input_schema(self, payload: Dict[str, Any]) -> bool:
        """Verifies that the input conforms to RFC 0001 KRM raw tree requirements."""
        pass

    @abstractmethod
    def validate_output_schema(self, result: Dict[str, Any]) -> bool:
        """Verifies that output contains valid node IDs, confidence scores, and provenance."""
        pass

    @abstractmethod
    def run_golden_benchmark((self) -> float:
        """Runs validation on standard test vectors and returns accuracy score >= 0.95."""
        pass
```

---

## 3. Automated Validation Runner

During `npm run lint` or `pytest tests/contracts`, the test runner executes strict verification:

1. **Schema Non-Null Verification:** Ensures no KRM node emits missing `id`, `node_type`, or `confidence_score` fields.
2. **Provenance BBox Invariants:** Validates that $x_0 < x_1$ and $y_0 < y_1$ for all bounding boxes.
3. **Idempotency Check:** Executing an analyzer twice on identical inputs must return identical AST hashes.
