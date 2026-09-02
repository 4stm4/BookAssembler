"""vision_fallback: Tunables, all overridable from the environment."""

import os

VISION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("KAE_VISION_CONFIDENCE_THRESHOLD", "0.45")
)

MAX_VISION_CALLS = int(os.environ.get("KAE_VISION_MAX_CALLS", "20"))

MAX_VISION_TIME = int(os.environ.get("KAE_VISION_MAX_TIME", "300"))
