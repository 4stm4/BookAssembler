# RFC 0015: Error Taxonomy and Text Desynchronization Metrics

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0015 defines the structured error taxonomy for KAE subsystems and details the quantitative metrics used to detect text desynchronization, OCR degradation, and table structural drift.

---

## 2. Error Categorization Hierarchy

KAE errors are categorized into distinct, actionable error domains:

```python
from enum import Enum

class ErrorCategory(str, Enum):
    STORAGE_READ_FAILURE = "STORAGE_READ_FAILURE"
    STORAGE_WRITE_FAILURE = "STORAGE_WRITE_FAILURE"
    ANALYZER_OCR_FAIL = "ANALYZER_OCR_FAIL"
    ANALYZER_TIKZ_SYNTAX_ERROR = "ANALYZER_TIKZ_SYNTAX_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    LLM_HALLUCINATION_DETECTED = "LLM_HALLUCINATION_DETECTED"
    DESYNC_TEXT_DRIFT = "DESYNC_TEXT_DRIFT"
    LATEX_COMPILATION_ERROR = "LATEX_COMPILATION_ERROR"
```

---

## 3. Text Desynchronization Metrics

When translating or restructuring technical text, KAE monitors 4 mathematical drift metrics:

### 3.1 Wagner-Fischer Levenshtein Distance
Measures edit operations (insertions, deletions, substitutions) between source assembly code / mathematical formulas and translated Markdown:

$$D(i,j) = \min \begin{cases} D(i-1, j) + 1 \\ D(i, j-1) + 1 \\ D(i-1, j-1) + \text{cost} \end{cases}$$

### 3.2 Tree Edit Distance for Structure (TEDS)
Evaluates structural fidelity of converted tables and TikZ trees:

$$\text{TEDS}(T_1, T_2) = 1 - \frac{\text{EditDistance}(T_1, T_2)}{\max(|T_1|, |T_2|)}$$

### 3.3 Word Error Rate (WER) & Character Error Rate (CER)
Measures OCR degradation in scanned technical manuals:

$$\text{WER} = \frac{S + D + I}{N}$$

### 3.4 F1 Alignment Score
F1 metric comparing technical term presence against the domain glossary dictionary (`RFC 0011`).

---

## 4. Automatic Escalation Rules

- If $\text{WER} > 0.15$ or $\text{TEDS} < 0.80$, the affected section status is automatically transitioned to `PENDING_HUMAN_REVIEW` for the reactive HITL workflow (`RFC 0016`).
