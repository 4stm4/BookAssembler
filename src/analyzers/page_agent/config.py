"""page_agent: Tunables, all overridable from the environment."""

import os

# Requests in flight. Modest on purpose: a page costs ~1.7s of inference and
# almost nothing in transfer, so there is little latency to hide, and a queue of
# concurrent generations on one GPU only makes each of them slower.
VISION_CONCURRENCY = int(os.environ.get("KAE_VISION_CONCURRENCY", "2"))

# Image fidelity. Measured against Qwen2.5-VL: a 512px page answers in ~1.7s,
# a 900px one did not return within 180s — inference cost climbs steeply with
# visual tokens, while the transfer is negligible either way (the uplink does
# ~300 KB/s, so an 8KB page leaves in milliseconds). Raise only against a timing
# measurement on the target GPU, never as a default "improvement".
RENDER_DPI = int(os.environ.get("KAE_VISION_DPI", "72"))

JPEG_QUALITY = int(os.environ.get("KAE_VISION_JPEG_QUALITY", "30"))

JPEG_MAX_DIM = int(os.environ.get("KAE_VISION_MAX_DIM", "512"))
