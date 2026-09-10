"""vision_fallback: Tunables, all overridable from the environment."""

import os

# RFC 0017 §4: below 0.60 a block is retried with the vision model before it is
# escalated to a human.
VISION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("KAE_VISION_CONFIDENCE_THRESHOLD", "0.60")
)

MAX_VISION_CALLS = int(os.environ.get("KAE_VISION_MAX_CALLS", "20"))

MAX_VISION_TIME = int(os.environ.get("KAE_VISION_MAX_TIME", "300"))
