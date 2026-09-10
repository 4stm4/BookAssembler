"""Reading the source file — the counterpart to access.py.

access.py reads KRM nodes already in memory; this module reads the document's
*origin*: resolving `doc.source_uri` back to a real PDF on disk, and turning a
rendered page into the small JPEG a vision agent is sent.

Both functions lived in page_agent, which made it a hidden dependency of
whatever else needed to render a page or find the source file — ocr and
api/app.py already reached into page_agent.rules for exactly this, and ocr
carried a same-named wrapper that did nothing but that import. Neither
function is a page_agent behaviour: PageAgentAnalyzer decides a page's role
and block types, not how source paths resolve or how pixmaps get encoded.
"""

import os
from typing import Any, Optional

from src.krm.models import KnowledgeDocument

# Measured against Qwen2.5-VL (RFC 0022): a 512px page answers in ~1.7s, a
# 900px one did not return within 180s — inference cost climbs steeply with
# visual tokens. Raise only against a timing measurement on the target GPU.
DEFAULT_JPEG_QUALITY = int(os.environ.get("KAE_VISION_JPEG_QUALITY", "30"))
DEFAULT_JPEG_MAX_DIM = int(os.environ.get("KAE_VISION_MAX_DIM", "512"))


def pixmap_to_jpeg(
    pixmap: Any,
    quality: int = DEFAULT_JPEG_QUALITY,
    max_dim: int = DEFAULT_JPEG_MAX_DIM,
) -> bytes:
    import io
    from PIL import Image
    img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    """Best-effort: resolve doc.source_uri to a local PDF file an agent can read.

    Handles sep://<provider>/<rel> (unknown provider id): tries every known
    SEP root; also file:// and absolute paths.
    """
    uri = doc.source_uri or ""
    if uri.startswith("file://"):
        p = uri[len("file://"):]
        return p if os.path.exists(p) else None
    if uri.startswith("upload://"):
        filename = uri.replace("upload://", "")
        ssd = os.environ.get("KAE_SSD_PATH", "/data/kae")
        for d in os.listdir(ssd) if os.path.isdir(ssd) else []:
            cand = os.path.join(ssd, d, filename)
            if os.path.isfile(cand):
                return cand
        return None
    if uri.startswith("sep://"):
        try:
            _, rel = uri.replace("sep://", "").split("/", 1)
        except ValueError:
            return None
        # Try both the env-configured SSD path and legacy /data/kae — SEP root
        # can move between deploys, but the file layout under it is stable.
        roots = [
            os.environ.get("KAE_SSD_PATH", "/data/kae"),
            "/data/kae", "/data/ssd",
        ]
        for root in roots:
            cand = os.path.join(root, rel)
            if os.path.exists(cand):
                return cand
        return None
    return uri if os.path.isabs(uri) and os.path.exists(uri) else None
