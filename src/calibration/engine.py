"""
Confidence Calibration Engine for Knowledge Assembly Engine (KAE).

Implements CalibrationMetrics and ConfidenceCalibrator according to RFC 0017.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, math)
"""

from dataclasses import dataclass
from typing import List


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
