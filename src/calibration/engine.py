"""
Confidence Calibration Engine for Knowledge Assembly Engine (KAE).

Implements CalibrationMetrics and ConfidenceCalibrator according to RFC 0017.

Raw LLM and analyzer confidences are overconfident, so a score is rescaled per
extraction category before anything downstream (HITL queueing, vision retry)
reads it.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, math)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

# Affine rescaling per extraction category (RFC 0017 §3): slope, intercept.
CATEGORY_RESCALING: Dict[str, Tuple[float, float]] = {
    "tikz_vectorization": (0.88, 0.05),
    "ocr_extraction": (0.95, 0.0),
}

# Operational thresholds (RFC 0017 §4).
AUTO_COMMIT_THRESHOLD = 0.85
RETRY_THRESHOLD = 0.60


class ConfidenceAction(str, Enum):
    """
    What the pipeline does with a node at a given calibrated confidence (RFC 0017 §4).
    """
    AUTO_COMMIT = "AUTO_COMMIT"
    HITL_REVIEW = "HITL_REVIEW"
    RETRY_FALLBACK = "RETRY_FALLBACK"


def confidence_action(calibrated_confidence: float) -> ConfidenceAction:
    if calibrated_confidence >= AUTO_COMMIT_THRESHOLD:
        return ConfidenceAction.AUTO_COMMIT
    if calibrated_confidence >= RETRY_THRESHOLD:
        return ConfidenceAction.HITL_REVIEW
    return ConfidenceAction.RETRY_FALLBACK


@dataclass
class CalibrationMetrics:
    """
    Metrics capturing Expected Calibration Error (ECE) and per-bin statistics.
    """
    ece_score: float
    bin_confidences: List[float]
    bin_accuracies: List[float]


class ConfidenceCalibrator:
    """
    Calibrator for assessing prediction confidence error and applying calibration shifts.
    """

    @staticmethod
    def compute_ece(
        predictions: List[float], ground_truth: List[bool], num_bins: int = 10
    ) -> CalibrationMetrics:
        """
        Computes Expected Calibration Error (ECE), bin confidences, and bin accuracies.
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("predictions and ground_truth lists must have equal length")

        total_samples = len(predictions)
        if total_samples == 0:
            return CalibrationMetrics(
                ece_score=0.0,
                bin_confidences=[0.0] * num_bins,
                bin_accuracies=[0.0] * num_bins,
            )

        bin_confidences: List[float] = [0.0] * num_bins
        bin_accuracies: List[float] = [0.0] * num_bins
        bin_counts: List[int] = [0] * num_bins

        bin_conf_sums: List[float] = [0.0] * num_bins
        bin_correct_sums: List[int] = [0] * num_bins

        for p, gt in zip(predictions, ground_truth):
            clamped_p = max(0.0, min(1.0, p))
            bin_idx = int(clamped_p * num_bins)
            if bin_idx >= num_bins:
                bin_idx = num_bins - 1

            bin_counts[bin_idx] += 1
            bin_conf_sums[bin_idx] += clamped_p
            if gt:
                bin_correct_sums[bin_idx] += 1

        ece_score = 0.0
        for i in range(num_bins):
            count = bin_counts[i]
            if count > 0:
                avg_conf = bin_conf_sums[i] / count
                avg_acc = float(bin_correct_sums[i]) / count
                bin_confidences[i] = avg_conf
                bin_accuracies[i] = avg_acc

                weight = float(count) / float(total_samples)
                ece_score += weight * abs(avg_acc - avg_conf)
            else:
                bin_confidences[i] = 0.0
                bin_accuracies[i] = 0.0

        return CalibrationMetrics(
            ece_score=ece_score,
            bin_confidences=bin_confidences,
            bin_accuracies=bin_accuracies,
        )

    def __init__(self) -> None:
        self._isotonic: Dict[str, List[Tuple[float, float]]] = {}

    def fit(
        self, category: str, predictions: List[float], ground_truth: List[bool]
    ) -> List[Tuple[float, float]]:
        """
        Fits an isotonic mapping raw -> empirical accuracy for a category from a
        golden benchmark set (RFC 0017 §3), replacing the affine default.
        """
        if len(predictions) != len(ground_truth):
            raise ValueError("predictions and ground_truth lists must have equal length")

        observed: Dict[float, List[float]] = {}
        for prediction, truth in zip(predictions, ground_truth):
            score = max(0.0, min(1.0, prediction))
            observed.setdefault(score, []).append(1.0 if truth else 0.0)
        if not observed:
            return []

        # Pool Adjacent Violators over the per-score accuracies: merge neighbours
        # until the fitted values are non-decreasing in the raw score.
        blocks: List[Tuple[List[float], float, int]] = [
            ([score], sum(outcomes) / len(outcomes), len(outcomes))
            for score, outcomes in sorted(observed.items())
        ]
        pooled: List[Tuple[List[float], float, int]] = []
        for block in blocks:
            while pooled and pooled[-1][1] > block[1]:
                prev_scores, prev_y, prev_n = pooled.pop()
                total = prev_n + block[2]
                block = (
                    prev_scores + block[0],
                    (prev_y * prev_n + block[1] * block[2]) / total,
                    total,
                )
            pooled.append(block)

        curve = [(score, y) for scores, y, _ in pooled for score in scores]
        self._isotonic[category] = curve
        return curve

    def calibrate_score(self, raw_confidence: float, category: str = "") -> float:
        """
        Maps a raw confidence to its empirical accuracy for the category
        (RFC 0017 §3). Uses a fitted isotonic curve when one exists, otherwise
        the shipped affine parameters; unknown categories pass through.
        """
        raw = max(0.0, min(1.0, raw_confidence))

        curve = self._isotonic.get(category)
        if curve:
            return _interpolate(curve, raw)

        slope, intercept = CATEGORY_RESCALING.get(category, (1.0, 0.0))
        return max(0.0, min(1.0, raw * slope + intercept))

    @staticmethod
    def calibrate_confidence(
        raw_confidence: float, ece_offset: float = 0.0
    ) -> float:
        """
        Applies temperature or offset calibration to raw confidence score, clamping to [0.0, 1.0].
        """
        calibrated = raw_confidence - ece_offset
        return max(0.0, min(1.0, calibrated))

    def calibrate(
        self, raw_confidence: float, ece_offset: float = 0.0
    ) -> float:
        """
        Instance alias for calibrate_confidence.
        """
        return self.calibrate_confidence(raw_confidence, ece_offset)


def _interpolate(curve: List[Tuple[float, float]], raw: float) -> float:
    """Piecewise-linear read of a fitted isotonic curve, flat outside its range."""
    if raw <= curve[0][0]:
        return curve[0][1]
    if raw >= curve[-1][0]:
        return curve[-1][1]

    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= raw <= x1:
            if x1 == x0:
                return y1
            ratio = (raw - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return curve[-1][1]
