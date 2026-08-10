# RFC 0017: Confidence Calibration Framework

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0017 specifies the statistical confidence calibration engine for KAE analyzers and LLM output scoring. Uncalibrated LLM confidence scores tend to be overconfident (e.g., claiming 99% certainty for erroneous assembly syntax). KAE applies Expected Calibration Error (ECE) optimization and isotonic regression to map raw probabilities to empirical accuracy.

---

## 2. Expected Calibration Error (ECE) Formula

To quantify analyzer calibration quality, predictions are partitioned into $M$ equally-spaced probability bins $B_m$:

$$\text{ECE} = \sum_{m=1}^{M} \frac{|B_m|}{N} \Big| \text{acc}(B_m) - \text{conf}(B_m) \Big|$$

where:
- $|B_m|$ is the number of samples in bin $m$.
- $\text{acc}(B_m)$ is the average true accuracy in bin $m$.
- $\text{conf}(B_m)$ is the average confidence score predicted in bin $m$.

---

## 3. Calibration Pipeline & Rescaling

```python
import numpy as np

class ConfidenceCalibrator:
    def __init__(self, bin_count: int = 10):
        self.bin_count = bin_count

    def calibrate_score(self, raw_confidence: float, category: str) -> float:
        """Applies isotonic scaling parameters trained on golden benchmark sets."""
        if category == "tikz_vectorization":
            # Rescale overconfident LLM score
            return float(np.clip(raw_confidence * 0.88 + 0.05, 0.0, 1.0))
        elif category == "ocr_extraction":
            return float(np.clip(raw_confidence * 0.95, 0.0, 1.0))
        return raw_confidence
```

---

## 4. Operational Thresholds

- **High Confidence ($\ge 0.85$):** Auto-committed to KRM without intervention.
- **Medium Confidence ($0.60 - 0.84$):** Enters HITL Queue (`RFC 0016`).
- **Low Confidence ($< 0.60$):** Retried automatically with fallback model / higher-resolution OCR prior to HITL escalation.
