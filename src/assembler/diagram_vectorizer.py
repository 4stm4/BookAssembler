"""
Diagram vectorizer — reconstructs a scanned schematic into vector TikZ.

RFC 0011 §2.2 defines diagram_extraction → tikz_vectorization as a transformation
chain. This module implements the CV side: it renders a DiagramBlock's source page
region, detects the box rectangles and connecting arrows with OpenCV, matches the
in-diagram text labels (already stored on the DiagramBlock) to the boxes, and emits
a TikZ picture that XeLaTeX compiles into a crisp vector diagram — not a raster crop.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

Rect = Tuple[int, int, int, int]  # x, y, w, h (pixels within the region image)


def _render_region(pdf_path: str, page_index: int, bbox: Any, dpi: int = 150):
    import pymupdf as fitz
    import numpy as np

    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    clip = fitz.Rect(bbox.x0 * pw, bbox.y0 * ph, bbox.x1 * pw, bbox.y1 * ph)
    pix = page.get_pixmap(clip=clip, dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n >= 3:
        img = img[:, :, :3]
    doc.close()
    return img


def _extract_words(pdf_path: str, page_index: int, bbox: Any) -> List[Dict[str, Any]]:
    """Word-level text inside the region, in region-normalized coords.

    OCR/text blocks glue neighbouring labels ("InstructionMemory"); words keep
    each token separately positioned, which is what box matching needs.
    """
    import pymupdf as fitz

    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    rx0, ry0 = bbox.x0 * pw, bbox.y0 * ph
    rw, rh = (bbox.x1 - bbox.x0) * pw, (bbox.y1 - bbox.y0) * ph
    words = []
    for w in page.get_text("words"):
        x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not (rx0 <= cx <= rx0 + rw and ry0 <= cy <= ry0 + rh):
            continue
        if not txt.strip():
            continue
        words.append({
            "text": txt,
            "lx0": (x0 - rx0) / max(1e-6, rw), "lx1": (x1 - rx0) / max(1e-6, rw),
            "ly0": (y0 - ry0) / max(1e-6, rh), "ly1": (y1 - ry0) / max(1e-6, rh),
            "cx": (cx - rx0) / max(1e-6, rw), "cy": (cy - ry0) / max(1e-6, rh),
        })
    doc.close()
    return words


def _detect_boxes(gray) -> List[Rect]:
    """Detect leaf rectangles (the diagram boxes), dropping big enclosing frames."""
    import cv2

    _, th = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes: List[Rect] = []
    for c in cnts:
        if cv2.contourArea(c) < 800:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.03 * peri, True)
        x, y, w, h = cv2.boundingRect(c)
        if len(approx) == 4 and w > 25 and h > 15 and 0.15 < w / max(1, h) < 12:
            boxes.append((x, y, w, h))

    # Drop boxes that enclose other boxes (group frames), keep the inner cells.
    def contains(a: Rect, b: Rect) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax <= bx and ay <= by and ax + aw >= bx + bw and ay + ah >= by + bh and (aw * ah) > (bw * bh)

    leaves = [b for b in boxes if not any(contains(b, o) for o in boxes if o != b)]
    # Deduplicate near-identical rectangles.
    uniq: List[Rect] = []
    for b in sorted(leaves, key=lambda r: -r[2] * r[3]):
        if not any(abs(b[0] - u[0]) < 12 and abs(b[1] - u[1]) < 12 and abs(b[2] - u[2]) < 12 and abs(b[3] - u[3]) < 12 for u in uniq):
            uniq.append(b)
    return uniq


def _match_labels_to_boxes(
    boxes: List[Rect], labels: List[Dict[str, Any]], iw: int, ih: int
) -> Tuple[Dict[int, str], Dict[int, str], List[str]]:
    """Assign each label to a box.

    Returns (inside_text, header_text, free_labels):
    - inside_text[bi]: label whose center falls inside box bi (the box content)
    - header_text[bi]: a title label sitting directly above box bi (with x-overlap)
    - free_labels: labels not attached to any box (e.g. "(a) Immediate", "EA*")
    """
    inside: Dict[int, str] = {}
    header: Dict[int, str] = {}
    used = [False] * len(labels)

    def overlaps_x(lx0: float, lx1: float, bx: float, bw: float) -> bool:
        return min(lx1, bx + bw) - max(lx0, bx) > 0.3 * min(lx1 - lx0, bw)

    # Pass 1: labels whose center is inside a box.
    for li, lab in enumerate(labels):
        cx, cy = lab["cx"] * iw, lab["cy"] * ih
        best = None
        for bi, (x, y, w, h) in enumerate(boxes):
            if x <= cx <= x + w and y <= cy <= y + h:
                if best is None or (w * h) < (boxes[best][2] * boxes[best][3]):
                    best = bi
        if best is not None:
            inside[best] = (inside[best] + " " + lab["text"]).strip() if best in inside else lab["text"]
            used[li] = True

    # Pass 2: remaining labels sitting directly above a box (titles).
    for li, lab in enumerate(labels):
        if used[li]:
            continue
        lx0, lx1 = lab["lx0"] * iw, lab["lx1"] * iw
        ly1 = lab["ly1"] * ih
        best, best_gap = None, 1e9
        for bi, (x, y, w, h) in enumerate(boxes):
            gap = y - ly1
            if 0 <= gap < 0.6 * h and gap < best_gap and overlaps_x(lx0, lx1, x, w):
                best, best_gap = bi, gap
        if best is not None:
            header[best] = (header[best] + " " + lab["text"]).strip() if best in header else lab["text"]
            used[li] = True

    free = [labels[li]["text"] for li in range(len(labels)) if not used[li]]
    return inside, header, free


def vectorize_diagram(
    pdf_path: str, page_index: int, bbox: Any, labels: List[Dict[str, Any]]
) -> str:
    """Return a TikZ picture reconstructing the diagram, or '' on failure."""
    try:
        import cv2
        import numpy as np

        img = _render_region(pdf_path, page_index, bbox)
        ih, iw = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        boxes = _detect_boxes(gray)
        if not boxes:
            return ""

        # Word-level text (region-normalized) — avoids glued OCR labels.
        region_labels = _extract_words(pdf_path, page_index, bbox)
        inside, header, free = _match_labels_to_boxes(boxes, region_labels, iw, ih)
        arrows = _detect_arrows(gray, boxes)

        import os

        # Preferred (RFC 0011): a cloud vision model reconstructs the diagram image
        # into TikZ directly — the only path that reaches ~99% on complex schematics.
        # Enabled when an API key is present; the CV facts are passed as a strong hint.
        if os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
            vt = _vision_tikz(img, boxes, inside, header, iw, ih)
            if vt:
                return vt

        # Local ollama vision agent (llava/qwen-vl) — no cloud, no API key. Best on
        # a GPU agent (incl. Colab); slow but usable on CPU. Opt-in via VISION_OLLAMA.
        if os.environ.get("VISION_OLLAMA_MODEL"):
            vt = _ollama_vision_tikz(img, inside, header, boxes)
            if vt:
                return vt

        # Local coder LLM: opt-in, degrades on weak CPU models (see notes on _llm_tikz).
        if os.environ.get("LLM_TIKZ_MODEL"):
            llm_tikz = _llm_tikz(boxes, inside, header, arrows, iw, ih)
            if llm_tikz:
                return llm_tikz

        # Deterministic CV fallback (works offline; good on simple diagrams).
        return _build_tikz(boxes, inside, header, arrows, iw, ih)
    except Exception:
        log.exception("Diagram vectorization failed on page %s", page_index)
        return ""


def _detect_arrows(gray, boxes: List[Rect]) -> List[Tuple[int, int]]:
    """Detect connections between boxes as (src_idx, dst_idx) pairs.

    Heuristic: a horizontal run of dark pixels between two boxes on roughly the
    same row implies a left→right arrow (the diagrams flow left to right).
    """
    import numpy as np

    conns: List[Tuple[int, int]] = []
    for i, (xi, yi, wi, hi) in enumerate(boxes):
        ci_y = yi + hi / 2
        for j, (xj, yj, wj, hj) in enumerate(boxes):
            if i == j:
                continue
            cj_y = yj + hj / 2
            # j is to the right of i, on a similar row, reasonably close.
            if xj > xi + wi and abs(cj_y - ci_y) < max(hi, hj) * 0.7 and (xj - (xi + wi)) < (wi + wj) * 2.5:
                gap_x0 = int(xi + wi)
                gap_x1 = int(xj)
                yy = int(ci_y)
                if gap_x1 - gap_x0 < 4:
                    continue
                strip = gray[max(0, yy - 3):yy + 3, gap_x0:gap_x1]
                if strip.size and float((strip < 120).mean()) > 0.15:
                    conns.append((i, j))
    return conns


def _build_tikz(
    boxes: List[Rect], inside: Dict[int, str], header: Dict[int, str],
    arrows: List[Tuple[int, int]], iw: int, ih: int
) -> str:
    """Emit a TikZ picture. Pixel coords → cm, Y flipped (image top-left origin)."""
    # Fit within a page: cap both width (~15cm) and height (~23cm), keep aspect.
    scale = min(15.0 / iw, 23.0 / ih)

    def px(x: float) -> float:
        return round(x * scale, 3)

    def py(y: float) -> float:
        return round((ih - y) * scale, 3)

    lines = [r"\begin{tikzpicture}[every node/.style={font=\footnotesize}]"]
    # Pin the canvas to the full region so the picture aligns 1:1 with the source
    # crop (no shift from content-only cropping) — critical for overlay/diff checks.
    lines.append(f"\\useasboundingbox (0,0) rectangle ({px(iw):.2f},{py(0):.2f});")
    for bi, (x, y, w, h) in enumerate(boxes):
        cx, cy = px(x + w / 2), py(y + h / 2)
        wcm, hcm = px(w), (h * scale)
        txt = _tex_escape(inside.get(bi, ""))
        lines.append(
            f"\\node[draw, minimum width={wcm:.2f}cm, minimum height={max(0.3, hcm):.2f}cm, "
            f"inner sep=1pt] (b{bi}) at ({cx:.2f},{cy:.2f}) {{{txt}}};"
        )
        if bi in header:
            lines.append(
                f"\\node[font=\\scriptsize, above=0.4pt of b{bi}] {{{_tex_escape(header[bi])}}};"
            )
    for s, d in arrows:
        lines.append(f"\\draw[-{{Latex[length=2mm]}}, thick] (b{s}.east) -- (b{d}.west);")
    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines)


def _llm_tikz(
    boxes: List[Rect], inside: Dict[int, str], header: Dict[int, str],
    arrows: List[Tuple[int, int]], iw: int, ih: int
) -> str:
    """Refine CV facts into TikZ via a coder LLM (RFC 0011 tikz_vectorization)."""
    import json as _json
    import os
    import urllib.request

    host = os.environ.get("LLM_TIKZ_URL", "http://192.168.88.71:11434")
    model = os.environ.get("LLM_TIKZ_MODEL", "qwen2.5-coder:3b")

    def _call(prompt: str) -> Optional[str]:
        payload = _json.dumps({
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.0, "seed": 42, "num_predict": 2560},
            "keep_alive": "10m",
        }).encode()
        req = urllib.request.Request(f"{host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return _json.loads(r.read()).get("response", "")
        except Exception:
            log.warning("TikZ LLM call failed")
            return None

    scale = min(15.0 / iw, 23.0 / ih)
    facts = []
    for bi, (x, y, w, h) in enumerate(boxes):
        cx = round((x + w / 2) * scale, 2)
        cy = round((ih - (y + h / 2)) * scale, 2)
        wcm = round(w * scale, 2)
        hcm = round(max(0.3, h * scale), 2)
        facts.append({
            "id": bi, "x": cx, "y": cy, "w": wcm, "h": hcm,
            "text": inside.get(bi, ""), "title": header.get(bi, ""),
        })
    prompt = (
        "You reconstruct a scanned block diagram as TikZ. Below are detected boxes "
        "with centimeter coordinates (x,y = center, origin bottom-left), size (w,h), "
        "the text inside each box, and an optional title above it. Arrows connect box "
        "ids left-to-right.\n\n"
        f"BOXES (JSON):\n{facts}\n\nARROWS (src->dst): {arrows}\n\n"
        "Output ONLY a LaTeX tikzpicture environment (\\begin{tikzpicture}...\\end{tikzpicture}). "
        "Rules: draw each box with \\node[draw,minimum width=Wcm,minimum height=Hcm] (bID) at (x,y) {text}; "
        "put the title as a small node above the box; draw arrows with \\draw[-{Latex}] (bSRC.east)--(bDST.west); "
        "merge boxes that are horizontally adjacent and share a title into one multi-cell box; "
        "keep the given coordinates. No explanation, no ```."
    )
    resp = _call(prompt)
    if not resp:
        return ""
    resp = resp.strip()
    if "\\begin{tikzpicture}" not in resp:
        return ""
    start = resp.index("\\begin{tikzpicture}")
    end = resp.rindex("\\end{tikzpicture}") + len("\\end{tikzpicture}")
    return resp[start:end]


_VISION_PROMPT = (
    "This image is a scanned block diagram from a computer-science textbook. "
    "Reconstruct it as a LaTeX TikZ picture that reproduces the boxes, their text "
    "labels, the titles above boxes, and the connecting arrows, preserving the "
    "left-to-right / top-to-bottom layout. Use \\node[draw] for boxes and "
    "\\draw[-{Latex}] for arrows. Multi-cell boxes (several labels in one frame) "
    "must be one box split by vertical rules. Output ONLY the tikzpicture "
    "environment, no explanation, no markdown fences."
)


def _extract_tikz(text: str) -> str:
    if "\\begin{tikzpicture}" not in text or "\\end{tikzpicture}" not in text:
        return ""
    s = text.index("\\begin{tikzpicture}")
    e = text.rindex("\\end{tikzpicture}") + len("\\end{tikzpicture}")
    return text[s:e]


def _encode_png_b64(img, max_side: int = 1288) -> str:
    """PNG+base64 of the image, downscaled so vision models accept it
    (llama3.2-vision works around ~1120px; huge crops cause 500/OOM)."""
    import base64
    import cv2

    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def _ollama_vision_tikz(img, inside, header, boxes) -> str:
    """tikz_vectorization via a local ollama vision model (llava/qwen-vl)."""
    import base64
    import json as _json
    import os
    import urllib.request

    import cv2

    host = os.environ.get("VISION_OLLAMA_URL", "http://192.168.88.71:11434")
    # Stronger vision models (llama3.2-vision / qwen2.5vl) beat llava for diagram→TikZ;
    # run them on a GPU agent (e.g. Colab) — see colab/kae_gpu_agent.ipynb.
    # llava/minicpm-v are supported by ollama's llama-server; llama3.2-vision
    # (mllama) is not in some builds — see colab/kae_gpu_agent.ipynb.
    model = os.environ.get("VISION_OLLAMA_MODEL", "llava:13b")
    b64 = _encode_png_b64(img)
    if not b64:
        return ""
    hint = "\nDetected boxes (id: text/title): " + "; ".join(
        f"{i}:{inside.get(i, '')!r}/{header.get(i, '')!r}" for i in range(len(boxes)))
    payload = _json.dumps({
        "model": model, "prompt": _VISION_PROMPT + hint, "images": [b64],
        "stream": False, "options": {"temperature": 0.0, "seed": 42, "num_predict": 3072},
        "keep_alive": "10m",
    }).encode()
    req = urllib.request.Request(f"{host}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return _extract_tikz(_json.loads(r.read()).get("response", ""))
    except Exception:
        log.exception("Ollama vision call failed")
        return ""


def _vision_tikz(img, boxes, inside, header, iw, ih) -> str:
    """Send the diagram image to a cloud vision model and get TikZ back.

    RFC 0011 tikz_vectorization with a strong model. Requires OPENAI_API_KEY or
    ANTHROPIC_API_KEY. The CV facts are appended as a hint to anchor the layout.
    """
    import json as _json
    import os
    import urllib.request

    b64 = _encode_png_b64(img)
    if not b64:
        return ""
    hint = "\nDetected boxes (id: text / title): " + "; ".join(
        f"{i}: {inside.get(i, '')!r}/{header.get(i, '')!r}" for i in range(len(boxes))
    )
    prompt = _VISION_PROMPT + hint

    anth = os.environ.get("ANTHROPIC_API_KEY")
    if anth:
        body = _json.dumps({
            "model": os.environ.get("VISION_MODEL", "claude-sonnet-5"),
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"content-type": "application/json", "x-api-key": anth,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = _json.loads(r.read())
                return _extract_tikz("".join(c.get("text", "") for c in data.get("content", [])))
        except Exception:
            log.exception("Anthropic vision call failed")
            return ""

    openai = os.environ.get("OPENAI_API_KEY")
    if openai:
        body = _json.dumps({
            "model": os.environ.get("VISION_MODEL", "gpt-4o"),
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"content-type": "application/json", "authorization": f"Bearer {openai}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = _json.loads(r.read())
                return _extract_tikz(data["choices"][0]["message"]["content"])
        except Exception:
            log.exception("OpenAI vision call failed")
            return ""
    return ""


def _tex_escape(text: str) -> str:
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                 ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")]:
        text = text.replace(a, b)
    return text
