"""ocr: Tunables, all overridable from the environment."""

import os

OCR_CONCURRENCY = int(os.environ.get("KAE_OCR_CONCURRENCY", "2"))

# Measured on a scanned Intel-3212 page against Qwen2.5-VL:
#   512px, 10KB -> 24.6s, 1094 characters, transcription correct
#   700px       -> no answer in 150s
#   900px       -> no answer in 180s
# The limit is a cliff, not a slope, so the page is capped at the size that
# demonstrably answers. Raising it only against a fresh timing measurement.
OCR_DPI = int(os.environ.get("KAE_OCR_DPI", "72"))

OCR_MAX_DIM = int(os.environ.get("KAE_OCR_MAX_DIM", "512"))

# 24.6s observed for ~1100 characters. A denser page generates more tokens and
# takes proportionally longer, so the classification timeout (45s) is too tight
# here — it would abandon pages that were about to answer.
OCR_TIMEOUT = int(os.environ.get("KAE_OCR_TIMEOUT", "150"))

# A timeout here means the page is too heavy for the model, not that the
# request was unlucky: repeating it costs minutes and changes nothing.
OCR_ATTEMPTS = int(os.environ.get("KAE_OCR_ATTEMPTS", "1"))
