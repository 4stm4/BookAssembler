#!/usr/bin/env python3
"""
Diagram extraction and primitive detection module.

Pipeline:
  1. crop_figure()      — вырезает фигуру из PDF по границам caption
  2. classify_image()   — определяет: схема, таблица, фото, код
  3. detect_primitives() — находит примитивы: rect, line, arrow, text
  4. measure()          — bbox, center, размеры в pt
  5. build_topology()   — кто с кем соединён, взаимное расположение
  6. generate_tikz()    — из топологии → TikZ код
  7. review_needed()    — что передать на проверку агенту

Usage:
    python3 src/diagram_extract.py -i book.pdf -c 4 -s 154 -e 217
    python3 src/diagram_extract.py -i book.pdf --page 174 --figure 4.10
"""

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

import cv2
import numpy as np

try:
    import fitz
except ImportError:
    print("ERROR: pip install pymupdf")
    sys.exit(1)

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
os.chdir(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class PrimitiveType(str, Enum):
    RECT = "rect"
    LINE = "line"
    ARROW = "arrow"
    TEXT = "text"
    ELLIPSE = "ellipse"
    UNKNOWN = "unknown"


class ImageClass(str, Enum):
    DIAGRAM = "diagram"
    TABLE = "table"
    PHOTO = "photo"
    CODE = "code"
    UNKNOWN = "unknown"


class ReviewReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    ARROW_MISSING = "arrow_missing"
    ARROW_AMBIGUOUS = "arrow_ambiguous"
    OVERLAP = "overlap"
    UNCLASSIFIED = "unclassified_primitive"
    OCR_UNCLEAR = "ocr_unclear"


@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self):
        return self.x + self.w // 2

    @property
    def cy(self):
        return self.y + self.h // 2

    @property
    def area(self):
        return self.w * self.h

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def overlaps(self, other: "BBox", threshold=0.3) -> bool:
        ix = max(0, min(self.right, other.right) - max(self.x, other.x))
        iy = max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        intersection = ix * iy
        smaller = min(self.area, other.area)
        if smaller == 0:
            return False
        return intersection / smaller > threshold

    def distance_to(self, other: "BBox") -> float:
        return math.hypot(self.cx - other.cx, self.cy - other.cy)

    def relative_position(self, other: "BBox") -> str:
        """Where is 'other' relative to self."""
        dx = other.cx - self.cx
        dy = other.cy - self.cy
        if abs(dx) > abs(dy):
            return "right" if dx > 0 else "left"
        return "below" if dy > 0 else "above"


@dataclass
class Primitive:
    id: int
    ptype: PrimitiveType
    bbox: BBox
    confidence: float = 1.0
    text: str = ""
    angle: float = 0.0  # for lines/arrows, degrees
    endpoints: list = field(default_factory=list)  # [(x1,y1), (x2,y2)] for lines
    arrowhead: Optional[str] = None  # "start", "end", "both", None
    contour: Optional[np.ndarray] = None

    def to_dict(self):
        d = asdict(self)
        d.pop("contour", None)
        d["ptype"] = self.ptype.value
        if self.arrowhead is None:
            d.pop("arrowhead")
        return d


@dataclass
class Connection:
    from_id: int
    to_id: int
    connector_id: int  # id of line/arrow primitive
    direction: Optional[str] = None  # "forward", "backward", "both", "none"


@dataclass
class ReviewItem:
    reason: ReviewReason
    primitive_id: Optional[int]
    description: str
    crop_region: Optional[BBox] = None


@dataclass
class DiagramAnalysis:
    figure_number: str
    page: int
    image_class: ImageClass
    classification_confidence: float
    primitives: list  # List[Primitive]
    connections: list  # List[Connection]
    reviews: list  # List[ReviewItem]
    image_size: tuple = (0, 0)  # (w, h)
    crop_bbox: Optional[BBox] = None

    def needs_review(self) -> bool:
        return len(self.reviews) > 0

    def to_dict(self):
        return {
            "figure": self.figure_number,
            "page": self.page,
            "class": self.image_class.value,
            "confidence": self.classification_confidence,
            "image_size": self.image_size,
            "primitives": [p.to_dict() for p in self.primitives],
            "connections": [asdict(c) for c in self.connections],
            "reviews": [asdict(r) for r in self.reviews],
        }


# ---------------------------------------------------------------------------
# 1. Crop figure from PDF
# ---------------------------------------------------------------------------

def crop_figure(pdf_path: str, page_num: int, figure_num: str, dpi=300) -> tuple:
    """
    Extract figure region from PDF page.
    Returns (image_np, bbox, caption_text).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    text = page.get_text()

    caption_pattern = rf"Figure\s+{re.escape(figure_num)}"
    # PDF text may have newlines inside "Figure 4.10"
    text_joined = re.sub(r'\s+', ' ', text)
    caption_match = re.search(caption_pattern, text_joined)

    full_pix = page.get_pixmap(dpi=dpi)
    full_img = np.frombuffer(full_pix.samples, dtype=np.uint8).reshape(
        full_pix.height, full_pix.width, full_pix.n
    )
    if full_pix.n == 4:
        full_img = cv2.cvtColor(full_img, cv2.COLOR_RGBA2BGR)
    elif full_pix.n == 1:
        full_img = cv2.cvtColor(full_img, cv2.COLOR_GRAY2BGR)

    scale = dpi / 72.0

    if caption_match:
        blocks = page.get_text("dict")["blocks"]
        caption_bbox = find_caption_bbox(blocks, figure_num, scale)
        figure_bbox = find_figure_region(full_img, caption_bbox, scale)
    else:
        figure_bbox = BBox(0, 0, full_img.shape[1], full_img.shape[0])

    x, y, w, h = figure_bbox.x, figure_bbox.y, figure_bbox.w, figure_bbox.h
    x = max(0, x)
    y = max(0, y)
    w = min(w, full_img.shape[1] - x)
    h = min(h, full_img.shape[0] - y)

    crop = full_img[y:y+h, x:x+w].copy()
    doc.close()
    return crop, figure_bbox, caption_match.group(0) if caption_match else ""


def find_caption_bbox(blocks: list, figure_num: str, scale: float) -> Optional[BBox]:
    """Find the bounding box of the figure caption text."""
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_text = ""
            for span in line.get("spans", []):
                line_text += span.get("text", "")
            if f"Figure {figure_num}" in line_text or f"Figure  {figure_num}" in line_text:
                bbox = line["bbox"]
                return BBox(
                    int(bbox[0] * scale),
                    int(bbox[1] * scale),
                    int((bbox[2] - bbox[0]) * scale),
                    int((bbox[3] - bbox[1]) * scale),
                )
    return None


def find_figure_region(img: np.ndarray, caption_bbox: Optional[BBox], scale: float) -> BBox:
    """
    Find the figure content region above the caption.
    Strategy: look for horizontal separator line, or scan for content boundary.
    """
    h, w = img.shape[:2]

    if caption_bbox is None:
        # No caption found — try to find figure by horizontal separator lines
        return find_figure_by_separator(img, scale)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    margin = int(30 * scale / 4)

    caption_top = caption_bbox.y
    # Search area: full width, above caption
    search_region = gray[:caption_top, :]

    # Strategy 1: find horizontal separator line above figure
    # (common in textbooks — a line separating text from figure)
    edges = cv2.Canny(search_region, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100,
                            minLineLength=w // 3, maxLineGap=20)
    separator_y = None
    if lines is not None:
        for line in lines:
            coords = line.flatten()
            x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
            # Horizontal line (within 3 degrees)
            if abs(y2 - y1) < max(abs(x2 - x1) * 0.05, 5):
                line_len = abs(x2 - x1)
                if line_len > w * 0.3:
                    if separator_y is None or y1 > separator_y:
                        # Take the lowest separator above caption as figure top
                        # But only if it's not too close to caption
                        if caption_top - y1 > h * 0.1:
                            separator_y = y1

    # Strategy 2: scan upward from caption
    top_y = 0
    if separator_y is not None:
        top_y = separator_y + int(5 * scale / 4)
    else:
        # Scan upward for empty gap
        for y in range(caption_top - 1, 0, -1):
            row = gray[y, :]
            dark_pixels = np.sum(row < 180)
            if dark_pixels < 3:
                empty_count = 0
                for y2 in range(y, max(0, y - int(40 * scale / 4)), -1):
                    if np.sum(gray[y2, :] < 180) < 3:
                        empty_count += 1
                    else:
                        break
                if empty_count > int(20 * scale / 4):
                    top_y = y
                    break

    # Find horizontal extent of content
    content_region = gray[top_y:caption_top, :]
    binary_content = (content_region < 180).astype(np.uint8)
    col_sums = np.sum(binary_content, axis=0)
    nonzero_cols = np.where(col_sums > 2)[0]
    if len(nonzero_cols) > 0:
        left = max(0, int(nonzero_cols[0]) - margin)
        right = min(w, int(nonzero_cols[-1]) + margin)
    else:
        left, right = 0, w

    return BBox(left, top_y, right - left, caption_top - top_y)


def find_figure_by_separator(img: np.ndarray, scale: float) -> BBox:
    """Fallback: find figure region using horizontal separator lines."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100,
                            minLineLength=w // 3, maxLineGap=20)
    separators = []
    if lines is not None:
        for line in lines:
            coords = line.flatten()
            x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
            if abs(y2 - y1) < max(abs(x2 - x1) * 0.05, 5):
                if abs(x2 - x1) > w * 0.3:
                    separators.append((y1 + y2) // 2)

    if len(separators) >= 2:
        separators.sort()
        # Figure is between first and last separator
        return BBox(0, separators[0], w, separators[-1] - separators[0])

    return BBox(0, 0, w, h)


# ---------------------------------------------------------------------------
# 2. Classify image
# ---------------------------------------------------------------------------

def classify_image(img: np.ndarray) -> tuple:
    """
    Determine if image is a diagram, table, photo, or code.
    Returns (ImageClass, confidence).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Feature: white ratio (diagrams are mostly white)
    white_ratio = np.sum(gray > 230) / (h * w)

    # Feature: number of unique intensity levels (photos have many, diagrams few)
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
    nonzero_bins = np.sum(hist > (h * w * 0.001))

    # Feature: straight lines (diagrams have many)
    edges = cv2.Canny(gray, 50, 150)
    lines_p = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=30,
                              minLineLength=min(w, h) // 8, maxLineGap=10)
    n_lines = len(lines_p) if lines_p is not None else 0

    # Feature: horizontal/vertical line ratio (tables have aligned lines)
    hv_lines = 0
    if lines_p is not None:
        for lp in lines_p:
            coords = lp.flatten()
            x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
            angle = abs(math.atan2(y2 - y1, x2 - x1))
            if angle < 0.1 or abs(angle - math.pi/2) < 0.1 or abs(angle - math.pi) < 0.1:
                hv_lines += 1

    # Feature: text density (code/tables have regular text patterns)
    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    small_contours = [c for c in contours if 20 < cv2.contourArea(c) < 500]
    text_density = len(small_contours) / max(1, h * w / 10000)

    # Decision logic
    scores = {
        ImageClass.DIAGRAM: 0.0,
        ImageClass.TABLE: 0.0,
        ImageClass.PHOTO: 0.0,
        ImageClass.CODE: 0.0,
    }

    # Diagrams: white background, few colors, some lines, some rectangles
    if white_ratio > 0.6:
        scores[ImageClass.DIAGRAM] += 0.3
    if n_lines > 3:
        scores[ImageClass.DIAGRAM] += 0.3
    if nonzero_bins < 15:
        scores[ImageClass.DIAGRAM] += 0.2

    # Tables: many horizontal+vertical lines, aligned
    if hv_lines > 5 and hv_lines / max(n_lines, 1) > 0.7:
        scores[ImageClass.TABLE] += 0.5
    if hv_lines > 10:
        scores[ImageClass.TABLE] += 0.3

    # Photos: many colors, few lines, low white ratio
    if nonzero_bins > 20:
        scores[ImageClass.PHOTO] += 0.4
    if white_ratio < 0.3:
        scores[ImageClass.PHOTO] += 0.3
    if n_lines < 3:
        scores[ImageClass.PHOTO] += 0.2

    # Code: high text density, mostly white, few lines
    if text_density > 3 and white_ratio > 0.5 and n_lines < 5:
        scores[ImageClass.CODE] += 0.6

    best = max(scores, key=scores.get)
    confidence = scores[best] / max(sum(scores.values()), 0.01)

    return best, round(confidence, 2)


# ---------------------------------------------------------------------------
# 3. Detect primitives
# ---------------------------------------------------------------------------

def detect_primitives(img: np.ndarray) -> list:
    """Find all primitives: text → erase → shapes → erase edges → lines."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=31, C=15
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    primitives = []
    pid = 0
    min_area = max(1500, (h * w) // 10000)

    # --- Layer 1: Text (small connected components) ---
    text_prims = detect_text_regions(binary, pid)
    primitives.extend(text_prims)
    pid += len(text_prims)

    # Erase text from binary
    binary_no_text = binary.copy()
    text_cc, _ = cv2.findContours(binary.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for tc in text_cc:
        area = cv2.contourArea(tc)
        x, y, tw, th = cv2.boundingRect(tc)
        if area < min_area and max(tw, th) < 120:
            cv2.rectangle(binary_no_text, (x - 2, y - 2),
                         (x + tw + 2, y + th + 2), 0, -1)

    # --- Layer 2: Shapes (contours on text-free binary) ---
    contours, _ = cv2.findContours(binary_no_text, cv2.RETR_LIST,
                                    cv2.CHAIN_APPROX_SIMPLE)
    raw_shapes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > (h * w) * 0.8:
            continue
        x, y, cw, ch = cv2.boundingRect(contour)
        bbox = BBox(x, y, cw, ch)
        ptype, confidence = classify_contour(contour, bbox, area, None)
        if ptype == PrimitiveType.UNKNOWN and confidence < 0.3:
            continue
        # Skip lines/arrows from contour detection — Hough handles them in Layer 3
        if ptype in (PrimitiveType.LINE, PrimitiveType.ARROW):
            continue

        p = Primitive(id=pid, ptype=ptype, bbox=bbox,
                      confidence=confidence, contour=contour)
        if ptype in (PrimitiveType.LINE, PrimitiveType.ARROW):
            endpoints = find_line_endpoints(contour)
            p.endpoints = endpoints
            if len(endpoints) == 2:
                dx = endpoints[1][0] - endpoints[0][0]
                dy = endpoints[1][1] - endpoints[0][1]
                p.angle = math.degrees(math.atan2(dy, dx))
            if ptype == PrimitiveType.ARROW:
                p.arrowhead = detect_arrowhead_direction(contour, endpoints)
        raw_shapes.append(p)
        pid += 1

    # Promote unknown → container, mark, dedup, filter
    rects_only = [p for p in raw_shapes if p.ptype == PrimitiveType.RECT]
    for p in raw_shapes:
        if p.ptype != PrimitiveType.UNKNOWN:
            continue
        contained = sum(1 for r in rects_only
                       if r.bbox.x >= p.bbox.x and r.bbox.y >= p.bbox.y
                       and r.bbox.right <= p.bbox.right
                       and r.bbox.bottom <= p.bbox.bottom)
        if contained >= 2:
            p.ptype = PrimitiveType.RECT
            p.confidence = 0.5
            p.text = "container"

    mark_containers(raw_shapes)
    raw_shapes = deduplicate_primitives(raw_shapes)
    min_side = max(60, min(w, h) // 50)
    raw_shapes = [p for p in raw_shapes
                  if p.ptype != PrimitiveType.RECT
                  or (p.bbox.w > min_side and p.bbox.h > min_side)]

    # Normalize rect sizes: snap similar widths/heights to median
    _normalize_rect_sizes(raw_shapes)

    # Infer missing containers from stacked rect groups
    _infer_containers(raw_shapes, binary_no_text)

    primitives.extend(raw_shapes)

    # --- Layer 3: Lines (Hough on binary without text and without rect edges) ---
    binary_clean = binary_no_text.copy()
    for p in raw_shapes:
        if p.ptype == PrimitiveType.RECT:
            b = p.bbox
            cv2.rectangle(binary_clean, (b.x - 10, b.y - 10),
                         (b.right + 10, b.bottom + 10), 0, -1)

    pid = len(primitives)
    hough_prims = detect_lines_hough(gray, binary_clean, raw_shapes, pid)

    # Try to form containers from H/V line pairs forming rectangles
    line_rects = _lines_to_rects(hough_prims, raw_shapes, pid + len(hough_prims))
    primitives.extend(line_rects)
    # Remove lines that were consumed into rects
    consumed_ids = set()
    for lr in line_rects:
        if hasattr(lr, '_source_line_ids'):
            consumed_ids.update(lr._source_line_ids)
    hough_prims = [lp for lp in hough_prims if lp.id not in consumed_ids]

    primitives.extend(hough_prims)

    # Re-number all
    for i, p in enumerate(primitives):
        p.id = i

    return primitives


def _normalize_rect_sizes(shapes: list):
    """Snap similar rect widths/heights to their median (within 3% tolerance)."""
    rects = [p for p in shapes if p.ptype == PrimitiveType.RECT]
    if len(rects) < 2:
        return

    # Group widths
    widths = sorted(set(r.bbox.w for r in rects))
    width_groups = []
    for wv in widths:
        placed = False
        for g in width_groups:
            if abs(wv - g[0]) / max(g[0], 1) < 0.08:
                g.append(wv)
                placed = True
                break
        if not placed:
            width_groups.append([wv])

    width_map = {}
    for g in width_groups:
        if len(g) > 1:
            median = sorted(g)[len(g) // 2]
            for v in g:
                width_map[v] = median

    # Group heights — compare to last element in group (chain tolerance)
    heights = sorted(set(r.bbox.h for r in rects))
    height_groups = []
    for hv in heights:
        placed = False
        for g in height_groups:
            if abs(hv - g[-1]) / max(g[-1], 1) < 0.05:
                g.append(hv)
                placed = True
                break
        if not placed:
            height_groups.append([hv])

    height_map = {}
    for g in height_groups:
        if len(g) > 1:
            median = sorted(g)[len(g) // 2]
            for v in g:
                height_map[v] = median

    # Apply width/height normalization
    for r in rects:
        new_w = width_map.get(r.bbox.w, r.bbox.w)
        new_h = height_map.get(r.bbox.h, r.bbox.h)
        r.bbox = BBox(r.bbox.x, r.bbox.y, new_w, new_h)

    # Snap x-coordinates: group rects with x within 10px
    x_vals = sorted(set(r.bbox.x for r in rects))
    x_map = {}
    x_groups = []
    for xv in x_vals:
        placed = False
        for g in x_groups:
            if abs(xv - g[0]) < 15:
                g.append(xv)
                placed = True
                break
        if not placed:
            x_groups.append([xv])
    for g in x_groups:
        if len(g) > 1:
            median = sorted(g)[len(g) // 2]
            for v in g:
                x_map[v] = median
    for r in rects:
        if r.bbox.x in x_map:
            r.bbox = BBox(x_map[r.bbox.x], r.bbox.y, r.bbox.w, r.bbox.h)


def _infer_containers(shapes: list, binary: np.ndarray):
    """Infer container rects from groups of vertically stacked rects."""
    rects = [p for p in shapes if p.ptype == PrimitiveType.RECT
             and not (p.text or "").startswith("container")]
    containers = [p for p in shapes if p.ptype == PrimitiveType.RECT
                  and (p.text or "").startswith("container")]

    # Group rects by similar x and width (same column)
    groups = []
    used = set()
    rects_sorted = sorted(rects, key=lambda r: r.bbox.y)
    for i, r in enumerate(rects_sorted):
        if i in used:
            continue
        group = [r]
        used.add(i)
        for j in range(i + 1, len(rects_sorted)):
            if j in used:
                continue
            s = rects_sorted[j]
            if abs(s.bbox.x - r.bbox.x) < 20 and abs(s.bbox.w - r.bbox.w) < 20:
                gap = s.bbox.y - group[-1].bbox.bottom
                if gap < 50:
                    group.append(s)
                    used.add(j)
        if len(group) >= 3:
            groups.append(group)

    max_id = max((p.id for p in shapes), default=0) + 1
    for group in groups:
        min_x = min(r.bbox.x for r in group) - 7
        min_y = min(r.bbox.y for r in group) - 7
        max_x = max(r.bbox.right for r in group) + 7
        max_y = max(r.bbox.bottom for r in group) + 7
        bbox = BBox(min_x, min_y, max_x - min_x, max_y - min_y)

        # Skip if already inside an existing container
        already_contained = False
        for c in containers:
            if (c.bbox.x <= bbox.x + 10 and c.bbox.y <= bbox.y + 10
                    and c.bbox.right >= bbox.right - 10
                    and c.bbox.bottom >= bbox.bottom - 10):
                already_contained = True
                break
        if already_contained:
            continue

        # Verify container border exists in binary
        p = Primitive(id=max_id, ptype=PrimitiveType.RECT,
                     bbox=bbox, confidence=0.5)
        p.text = "container"
        shapes.append(p)
        containers.append(p)
        max_id += 1


def _lines_to_rects(hough_prims: list, existing_rects: list, start_id: int) -> list:
    """Find 4 H/V lines forming a closed rectangle and create a container."""
    h_lines = []
    v_lines = []
    for p in hough_prims:
        if not p.endpoints or len(p.endpoints) != 2:
            continue
        ep1, ep2 = p.endpoints
        dx = abs(ep2[0] - ep1[0])
        dy = abs(ep2[1] - ep1[1])
        length = math.hypot(dx, dy)
        if length < 100:
            continue
        if dy < dx * 0.1:
            h_lines.append(p)
        elif dx < dy * 0.1:
            v_lines.append(p)

    new_rects = []
    used_line_ids = set()

    for vl1 in v_lines:
        for vl2 in v_lines:
            if vl1.id >= vl2.id:
                continue
            vx1 = vl1.endpoints[0][0]
            vx2 = vl2.endpoints[0][0]
            if abs(vx1 - vx2) < 100:
                continue
            vy1_min = min(vl1.endpoints[0][1], vl1.endpoints[1][1])
            vy1_max = max(vl1.endpoints[0][1], vl1.endpoints[1][1])
            vy2_min = min(vl2.endpoints[0][1], vl2.endpoints[1][1])
            vy2_max = max(vl2.endpoints[0][1], vl2.endpoints[1][1])

            # Check for matching H lines at top and bottom
            top_y = max(vy1_min, vy2_min)
            bot_y = min(vy1_max, vy2_max)
            if bot_y - top_y < 100:
                continue

            top_h = None
            bot_h = None
            for hl in h_lines:
                hy = hl.endpoints[0][1]
                hx_min = min(hl.endpoints[0][0], hl.endpoints[1][0])
                hx_max = max(hl.endpoints[0][0], hl.endpoints[1][0])
                lx = min(vx1, vx2)
                rx = max(vx1, vx2)
                if hx_min > lx + 30 or hx_max < rx - 30:
                    continue
                if abs(hy - top_y) < 30:
                    top_h = hl
                elif abs(hy - bot_y) < 30:
                    bot_h = hl

            if top_h and bot_h:
                lx = min(vx1, vx2)
                rx = max(vx1, vx2)
                ty = top_y
                by = bot_y
                bbox = BBox(lx, ty, rx - lx, by - ty)

                # Check not duplicate of existing rect
                is_dup = False
                for er in existing_rects:
                    if er.ptype != PrimitiveType.RECT:
                        continue
                    if (abs(er.bbox.x - bbox.x) < 30 and abs(er.bbox.y - bbox.y) < 30
                            and abs(er.bbox.w - bbox.w) < 30 and abs(er.bbox.h - bbox.h) < 30):
                        is_dup = True
                        break
                if is_dup:
                    continue

                # Count existing rects inside
                contained = sum(1 for er in existing_rects
                               if er.ptype == PrimitiveType.RECT
                               and er.bbox.x >= bbox.x - 10
                               and er.bbox.y >= bbox.y - 10
                               and er.bbox.right <= bbox.right + 10
                               and er.bbox.bottom <= bbox.bottom + 10)

                p = Primitive(id=start_id + len(new_rects),
                             ptype=PrimitiveType.RECT,
                             bbox=bbox, confidence=0.6)
                p.text = "container" if contained >= 2 else ""
                p._source_line_ids = {vl1.id, vl2.id, top_h.id, bot_h.id}
                new_rects.append(p)
                used_line_ids.update(p._source_line_ids)

    return new_rects


def detect_lines_hough(gray: np.ndarray, binary: np.ndarray,
                       existing: list, start_id: int) -> list:
    """Detect lines/arrows via HoughLinesP that contour method missed."""
    h, w = gray.shape

    lines = cv2.HoughLinesP(binary, 1, np.pi/180, threshold=40,
                            minLineLength=max(40, min(w, h) // 15),
                            maxLineGap=15)
    if lines is None:
        return []

    primitives = []
    pid = start_id

    for line in lines:
        coords = line.flatten()
        x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
        length = math.hypot(x2 - x1, y2 - y1)
        angle_rad = math.atan2(y2 - y1, x2 - x1)
        angle_deg = math.degrees(angle_rad)

        if length < 40:
            continue

        is_diagonal = not (abs(angle_deg) < 15 or abs(abs(angle_deg) - 90) < 15 or
                           abs(abs(angle_deg) - 180) < 15)

        if not is_diagonal and length > max(w, h) * 0.5:
            continue

        # Only check arrowheads on diagonal lines (H/V endpoints near rect corners cause false positives)
        arrowhead = None
        if is_diagonal:
            has_arrow = check_arrowhead_at_point(binary, (x2, y2), angle_rad)
            has_arrow_start = check_arrowhead_at_point(binary, (x1, y1), angle_rad + math.pi)
            if has_arrow and has_arrow_start:
                arrowhead = "both"
            elif has_arrow:
                arrowhead = "end"
            elif has_arrow_start:
                arrowhead = "start"
        ptype = PrimitiveType.ARROW if arrowhead else PrimitiveType.LINE

        bx = min(x1, x2)
        by = min(y1, y2)
        bw = abs(x2 - x1) + 1
        bh = abs(y2 - y1) + 1

        p = Primitive(
            id=pid,
            ptype=ptype,
            bbox=BBox(bx, by, bw, bh),
            confidence=0.7,
            angle=angle_deg,
            endpoints=[(x1, y1), (x2, y2)],
            arrowhead=arrowhead,
        )
        primitives.append(p)
        pid += 1

    # Merge collinear Hough lines: if two lines are parallel and close
    # perpendicularly, merge into one spanning their combined extent
    merged = sorted(primitives, key=lambda x: max(x.bbox.w, x.bbox.h), reverse=True)
    result = []
    used = set()
    for i, p in enumerate(merged):
        if i in used:
            continue
        ep1, ep2 = p.endpoints
        p_horiz = abs(ep1[1] - ep2[1]) < 15
        p_vert = abs(ep1[0] - ep2[0]) < 15
        if not (p_horiz or p_vert):
            # Dedup diagonal lines: if endpoints are close, keep longest
            is_dup = False
            for kept in result:
                if not kept.endpoints:
                    continue
                ke1, ke2 = kept.endpoints
                d_fwd = max(math.hypot(ep1[0]-ke1[0], ep1[1]-ke1[1]),
                            math.hypot(ep2[0]-ke2[0], ep2[1]-ke2[1]))
                d_rev = max(math.hypot(ep1[0]-ke2[0], ep1[1]-ke2[1]),
                            math.hypot(ep2[0]-ke1[0], ep2[1]-ke1[1]))
                if min(d_fwd, d_rev) < 100:
                    is_dup = True
                    break
            if not is_dup:
                result.append(p)
            continue
        # Find collinear lines to merge
        group_eps = [ep1, ep2]
        for j in range(i + 1, len(merged)):
            if j in used:
                continue
            q = merged[j]
            qe1, qe2 = q.endpoints
            if p_horiz:
                q_horiz = abs(qe1[1] - qe2[1]) < 15
                if not q_horiz:
                    continue
                perp_dist = abs((ep1[1] + ep2[1]) / 2 - (qe1[1] + qe2[1]) / 2)
                par_overlap = min(max(ep1[0], ep2[0]), max(qe1[0], qe2[0])) - \
                              max(min(ep1[0], ep2[0]), min(qe1[0], qe2[0]))
            else:
                q_vert = abs(qe1[0] - qe2[0]) < 15
                if not q_vert:
                    continue
                perp_dist = abs((ep1[0] + ep2[0]) / 2 - (qe1[0] + qe2[0]) / 2)
                par_overlap = min(max(ep1[1], ep2[1]), max(qe1[1], qe2[1])) - \
                              max(min(ep1[1], ep2[1]), min(qe1[1], qe2[1]))
            if perp_dist < 15 and par_overlap > -400:
                group_eps.extend([qe1, qe2])
                used.add(j)
        # Build merged line from extreme points
        if p_horiz:
            all_x = [e[0] for e in group_eps]
            avg_y = int(sum(e[1] for e in group_eps) / len(group_eps))
            new_ep1 = (min(all_x), avg_y)
            new_ep2 = (max(all_x), avg_y)
        else:
            all_y = [e[1] for e in group_eps]
            avg_x = int(sum(e[0] for e in group_eps) / len(group_eps))
            new_ep1 = (avg_x, min(all_y))
            new_ep2 = (avg_x, max(all_y))
        p.endpoints = [new_ep1, new_ep2]
        p.bbox = BBox(min(new_ep1[0], new_ep2[0]), min(new_ep1[1], new_ep2[1]),
                       abs(new_ep2[0] - new_ep1[0]) + 1, abs(new_ep2[1] - new_ep1[1]) + 1)
        result.append(p)

    return result


def check_arrowhead_at_point(binary: np.ndarray, point: tuple,
                             line_angle: float, radius=30) -> bool:
    """Check for arrowhead by comparing pixel density near tip vs along shaft."""
    h, w = binary.shape
    px, py = int(point[0]), int(point[1])

    dx = math.cos(line_angle)
    dy = math.sin(line_angle)

    def count_in_circle(cx, cy, r):
        total = 0
        filled = 0
        for iy in range(max(0, cy - r), min(h, cy + r + 1)):
            for ix in range(max(0, cx - r), min(w, cx + r + 1)):
                if (ix - cx) ** 2 + (iy - cy) ** 2 <= r * r:
                    total += 1
                    if binary[iy, ix] > 0:
                        filled += 1
        return filled, max(total, 1)

    # Density at the tip
    tip_filled, tip_total = count_in_circle(px, py, 15)
    tip_density = tip_filled / tip_total

    # Density along the shaft (30-50px back from tip)
    sx = int(px - dx * 40)
    sy = int(py - dy * 40)
    if not (0 <= sx < w and 0 <= sy < h):
        return False
    shaft_filled, shaft_total = count_in_circle(sx, sy, 15)
    shaft_density = shaft_filled / shaft_total

    # Arrowhead: tip area is significantly denser than shaft
    return tip_density > shaft_density * 1.5 and tip_density > 0.1


def mark_containers(primitives: list):
    """Mark rects that fully contain other rects as containers (lower confidence)."""
    rects = [p for p in primitives if p.ptype == PrimitiveType.RECT
             and p.text != "container"]
    for outer in rects:
        contained = 0
        for inner in rects:
            if inner is outer:
                continue
            if (inner.bbox.x >= outer.bbox.x and
                inner.bbox.y >= outer.bbox.y and
                inner.bbox.right <= outer.bbox.right and
                inner.bbox.bottom <= outer.bbox.bottom):
                contained += 1
        if contained >= 2:
            outer.confidence = 0.5
            outer.text = "container"


def deduplicate_primitives(primitives: list) -> list:
    """Remove duplicate/near-overlapping primitives, keep higher confidence."""
    if not primitives:
        return []

    # Sort by area descending
    sorted_prims = sorted(primitives, key=lambda p: p.bbox.area, reverse=True)
    kept = []

    for p in sorted_prims:
        is_dup = False
        for existing in kept:
            if p.ptype != existing.ptype:
                continue
            # Don't dedup containers vs regular rects
            is_container_pair = (
                (p.text == "container" and existing.text != "container") or
                (p.text != "container" and existing.text == "container")
            )
            if is_container_pair:
                continue
            if p.bbox.overlaps(existing.bbox, threshold=0.7):
                is_dup = True
                break
        if not is_dup:
            kept.append(p)

    return kept


def classify_contour(contour, bbox: BBox, area: float, hier_entry) -> tuple:
    """Classify a contour as rect, line, arrow, ellipse, or unknown."""
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    n_vertices = len(approx)

    aspect = bbox.w / max(bbox.h, 1)
    extent = area / max(bbox.area, 1)
    is_thin = min(bbox.w, bbox.h) < max(bbox.w, bbox.h) * 0.15

    # Rectangle: 4 corners, high extent
    if n_vertices == 4 and extent > 0.7 and not is_thin:
        return PrimitiveType.RECT, 0.9

    # Rectangle with slight imperfection
    if 4 <= n_vertices <= 6 and extent > 0.6 and not is_thin:
        return PrimitiveType.RECT, 0.7

    # Ellipse: many vertices, high extent, roughly circular, NOT tiny (text chars)
    if n_vertices > 6 and extent > 0.6 and min(bbox.w, bbox.h) > 30 and bbox.area > 4000:
        circularity = 4 * math.pi * area / (peri * peri + 1e-6)
        aspect_ratio = max(bbox.w, bbox.h) / max(min(bbox.w, bbox.h), 1)
        if circularity > 0.5 and aspect_ratio < 3:
            return PrimitiveType.ELLIPSE, 0.8

    # Line: thin and elongated
    if is_thin and (bbox.w > 30 or bbox.h > 30):
        if has_arrowhead(contour, bbox):
            return PrimitiveType.ARROW, 0.8
        return PrimitiveType.LINE, 0.8

    # Arrow: thin with triangular end
    if is_thin and n_vertices >= 5:
        if has_arrowhead(contour, bbox):
            return PrimitiveType.ARROW, 0.7

    # Diagonal line/arrow: bbox is not thin but contour is thin along its axis
    if not is_thin and min(bbox.w, bbox.h) > 30:
        diag_len = math.hypot(bbox.w, bbox.h)
        actual_width = area / max(diag_len, 1)
        if actual_width < diag_len * 0.15 and diag_len > 100:
            if has_arrowhead(contour, bbox):
                return PrimitiveType.ARROW, 0.7
            return PrimitiveType.LINE, 0.6

    return PrimitiveType.UNKNOWN, 0.3


def has_arrowhead(contour, bbox: BBox) -> bool:
    """Detect if a thin contour has an arrowhead (triangle at one end)."""
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.03 * peri, True)

    if len(approx) < 5:
        return False

    # An arrow typically has 7 vertices (shaft + head)
    # Check if one end is wider than the other
    points = approx.reshape(-1, 2)

    if bbox.w > bbox.h:
        # Horizontal arrow — check left vs right width
        left_points = points[points[:, 0] < bbox.cx]
        right_points = points[points[:, 0] >= bbox.cx]
        if len(left_points) < 2 or len(right_points) < 2:
            return False
        left_spread = np.ptp(left_points[:, 1]) if len(left_points) > 0 else 0
        right_spread = np.ptp(right_points[:, 1]) if len(right_points) > 0 else 0
        ratio = max(left_spread, right_spread) / max(min(left_spread, right_spread), 1)
        return ratio > 1.8
    else:
        # Vertical arrow
        top_points = points[points[:, 1] < bbox.cy]
        bottom_points = points[points[:, 1] >= bbox.cy]
        if len(top_points) < 2 or len(bottom_points) < 2:
            return False
        top_spread = np.ptp(top_points[:, 0]) if len(top_points) > 0 else 0
        bottom_spread = np.ptp(bottom_points[:, 0]) if len(bottom_points) > 0 else 0
        ratio = max(top_spread, bottom_spread) / max(min(top_spread, bottom_spread), 1)
        return ratio > 1.8


def detect_arrowhead_direction(contour, endpoints: list) -> str:
    """Determine which end of an arrow has the arrowhead."""
    if len(endpoints) < 2:
        return "end"

    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.03 * peri, True)
    points = approx.reshape(-1, 2)

    p1 = np.array(endpoints[0])
    p2 = np.array(endpoints[1])

    # Check point density near each endpoint — arrowhead has more points
    r = 15
    near_p1 = np.sum(np.linalg.norm(points - p1, axis=1) < r)
    near_p2 = np.sum(np.linalg.norm(points - p2, axis=1) < r)

    if near_p1 > near_p2 + 1:
        return "start"
    elif near_p2 > near_p1 + 1:
        return "end"
    return "end"  # default


def find_line_endpoints(contour) -> list:
    """Find the two extreme points of a line/arrow contour."""
    points = contour.reshape(-1, 2)
    if len(points) < 2:
        return []

    # Find two points with maximum distance
    max_dist = 0
    p1, p2 = points[0], points[-1]
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = np.linalg.norm(points[i] - points[j])
            if d > max_dist:
                max_dist = d
                p1, p2 = points[i], points[j]

    return [tuple(int(v) for v in p1), tuple(int(v) for v in p2)]


def detect_text_regions(binary: np.ndarray, start_id: int) -> list:
    """Detect text regions as groups of small connected components."""
    # Find small components (individual characters)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    char_bboxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if 15 < area < 800:
            x, y, w, h = cv2.boundingRect(c)
            if 4 < h < 40 and 2 < w < 40:
                char_bboxes.append(BBox(x, y, w, h))

    if not char_bboxes:
        return []

    # Cluster nearby chars into text regions
    text_groups = cluster_bboxes(char_bboxes, x_gap=12, y_gap=5)

    primitives = []
    pid = start_id
    for group in text_groups:
        if len(group) < 2:
            continue
        min_x = min(b.x for b in group)
        min_y = min(b.y for b in group)
        max_x = max(b.right for b in group)
        max_y = max(b.bottom for b in group)
        bbox = BBox(min_x, min_y, max_x - min_x, max_y - min_y)
        primitives.append(Primitive(
            id=pid,
            ptype=PrimitiveType.TEXT,
            bbox=bbox,
            confidence=0.8,
        ))
        pid += 1

    return primitives


def cluster_bboxes(bboxes: list, x_gap=15, y_gap=8) -> list:
    """Group bboxes that are close together (text on same line)."""
    if not bboxes:
        return []

    sorted_boxes = sorted(bboxes, key=lambda b: (b.y, b.x))
    groups = [[sorted_boxes[0]]]

    for box in sorted_boxes[1:]:
        merged = False
        for group in groups:
            for member in group:
                if (abs(box.cy - member.cy) < y_gap and
                    abs(box.x - member.right) < x_gap):
                    group.append(box)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            groups.append([box])

    return groups


# ---------------------------------------------------------------------------
# 4. Measure (already in BBox/Primitive)
# ---------------------------------------------------------------------------

def ocr_primitives(img: np.ndarray, pdf_path: str, page_num: int,
                    crop_bbox: BBox, primitives: list, dpi=300):
    """Fill text field using full-image Tesseract OCR (PSM 11 sparse text)."""
    try:
        import pytesseract
    except ImportError:
        return

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Full-image OCR with sparse text mode — finds all labels including tiny ones
    big = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, otsu = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    data = pytesseract.image_to_data(otsu, config='--psm 11',
                                      output_type=pytesseract.Output.DICT)
    # Common OCR corrections for 8086 diagrams
    ocr_fixes = {
        "oP": "SP", "Sl": "SI", "Dl": "DI", "Cl": "CI",
        "KX": "XX", "BxX": "BX", "AX,BxX": "AX,BX",
        "DABC": "0ABC", "dss": "", "(al": "(a)",
    }

    ocr_items = []
    for i in range(len(data['text'])):
        t = data['text'][i].strip()
        conf = int(data['conf'][i])
        if not t or conf < 30:
            continue
        t = re.sub(r'[^A-Za-z0-9,.\-/()\[\] ]+', '', t).strip()
        if not t:
            continue
        # Apply fixes
        t = ocr_fixes.get(t, t)
        if not t:
            continue
        ocr_items.append({
            "text": t,
            "conf": conf,
            "bbox": BBox(data['left'][i] // 2, data['top'][i] // 2,
                         data['width'][i] // 2, data['height'][i] // 2),
        })

    # Phase 1: fill text INSIDE rect/ellipse primitives
    # Process smaller shapes first, so containers don't steal text from inner rects
    shapes = [p for p in primitives
              if p.ptype in (PrimitiveType.RECT, PrimitiveType.ELLIPSE)]
    shapes.sort(key=lambda p: p.bbox.area)
    claimed_items = set()

    for p in shapes:
        if p.text and p.text != "container":
            continue
        inside = []
        for idx, item in enumerate(ocr_items):
            if idx in claimed_items:
                continue
            if (item["bbox"].cx >= p.bbox.x and item["bbox"].cx <= p.bbox.right and
                item["bbox"].cy >= p.bbox.y and item["bbox"].cy <= p.bbox.bottom):
                inside.append((idx, item))
        if inside:
            inside.sort(key=lambda t: (t[1]["bbox"].y, t[1]["bbox"].x))
            if p.text == "container":
                # Container only claims title-like text (>2 chars, not register names)
                known_regs = {"AX","BX","CX","DX","SI","DI","SP","BP",
                              "CS","DS","ES","SS","IP"}
                title_items = [(idx, item) for idx, item in inside
                               if item["text"] not in known_regs
                               and (len(item["text"]) >= 3 or " " in item["text"])]
                if title_items:
                    p.text = "container:" + " ".join(t[1]["text"] for t in title_items)
                    for idx, _ in title_items:
                        claimed_items.add(idx)
            else:
                p.text = " ".join(t[1]["text"] for t in inside)
                for idx, _ in inside:
                    claimed_items.add(idx)

    # Phase 2: fill TEXT primitives
    for p in primitives:
        if p.ptype != PrimitiveType.TEXT or p.text:
            continue
        inside = [item for item in ocr_items
                  if (item["bbox"].cx >= p.bbox.x - 20 and
                      item["bbox"].cx <= p.bbox.right + 20 and
                      item["bbox"].cy >= p.bbox.y - 10 and
                      item["bbox"].cy <= p.bbox.bottom + 10)]
        if inside:
            inside.sort(key=lambda t: (t["bbox"].y, t["bbox"].x))
            p.text = " ".join(t["text"] for t in inside)

    # Phase 3: create label primitives for OCR text NOT already claimed
    used_items = set()
    for item in ocr_items:
        if id(item) in claimed_items:
            continue
        # Check if this text is already represented by an existing TEXT primitive
        already_covered = False
        for p in primitives:
            if p.ptype == PrimitiveType.TEXT and p.text == item["text"]:
                if p.bbox.overlaps(item["bbox"], threshold=0.3):
                    already_covered = True
                    break
        if not already_covered and len(item["text"]) >= 2:
            used_items.add(id(item))

    # Add standalone OCR labels as new text primitives
    next_id = max((p.id for p in primitives), default=0) + 1
    for item in ocr_items:
        if id(item) in used_items:
            primitives.append(Primitive(
                id=next_id,
                ptype=PrimitiveType.TEXT,
                bbox=item["bbox"],
                confidence=item["conf"] / 100.0,
                text=item["text"],
            ))
            next_id += 1


def postprocess_ocr(primitives: list):
    """Verify and fix OCR results. Runs after all OCR is done."""
    # Known register labels — if OCR is close, fix it
    known_labels = {"AX", "BX", "CX", "DX", "AH", "AL", "BH", "BL",
                    "CH", "CL", "DH", "DL", "SI", "DI", "SP", "BP",
                    "CS", "DS", "ES", "SS", "IP", "FLAGS",
                    "AX,BX", "AX,CX", "AX,DX"}

    for p in primitives:
        if not p.text or p.text.startswith("container"):
            continue
        t = p.text.strip()

        # Fix common OCR substitutions for 2-char register names
        if len(t) == 2 and t not in known_labels:
            fixes_2 = {"oP": "SP", "Sl": "SI", "Dl": "DI", "0I": "DI",
                        "0S": "DS", "lP": "IP", "0X": "DX", "8X": "BX",
                        "5S": "SS", "E5": "ES"}
            if t in fixes_2:
                p.text = fixes_2[t]

        # Remove garbage: random short words that aren't hex/register/known
        words = t.split()
        if len(words) >= 2 and all(len(w) <= 3 for w in words):
            clean = []
            for w in words:
                if (w.upper() in known_labels or
                    re.match(r'^[0-9A-Fa-f]+$', w) or
                    len(w) > 2):
                    clean.append(w)
            if clean:
                p.text = " ".join(clean)
            else:
                p.text = ""

    # Remove primitives with empty text that are TEXT type
    to_remove = []
    for i, p in enumerate(primitives):
        if p.ptype == PrimitiveType.TEXT and not p.text:
            to_remove.append(i)
    for i in reversed(to_remove):
        primitives.pop(i)


def associate_text_to_shapes(primitives: list, max_gap=120):
    """Associate TEXT primitives with nearest RECT/ELLIPSE as labels."""
    shapes = [p for p in primitives
              if p.ptype in (PrimitiveType.RECT, PrimitiveType.ELLIPSE)
              and p.text != "container"]
    texts = [p for p in primitives if p.ptype == PrimitiveType.TEXT and p.text]

    for t in texts:
        best_shape = None
        best_dist = max_gap
        for s in shapes:
            dx = max(s.bbox.x - t.bbox.cx, 0, t.bbox.cx - s.bbox.right)
            dy = max(s.bbox.y - t.bbox.cy, 0, t.bbox.cy - s.bbox.bottom)
            dist = math.hypot(dx, dy)
            if dist < best_dist:
                best_dist = dist
                best_shape = s
        if best_shape and not best_shape.text:
            best_shape.text = t.text


def measure_primitives(primitives: list, dpi=300) -> dict:
    """Convert pixel measurements to points (1pt = 1/72 inch)."""
    scale = 72.0 / dpi
    measurements = {}
    for p in primitives:
        measurements[p.id] = {
            "type": p.ptype.value,
            "x_pt": round(p.bbox.x * scale, 1),
            "y_pt": round(p.bbox.y * scale, 1),
            "w_pt": round(p.bbox.w * scale, 1),
            "h_pt": round(p.bbox.h * scale, 1),
            "cx_pt": round(p.bbox.cx * scale, 1),
            "cy_pt": round(p.bbox.cy * scale, 1),
        }
    return measurements


# ---------------------------------------------------------------------------
# 5. Build topology
# ---------------------------------------------------------------------------

def build_topology(primitives: list, img_size: tuple = (0, 0)) -> list:
    """Determine connections between primitives."""
    connections = []
    rects = [p for p in primitives
             if p.ptype in (PrimitiveType.RECT, PrimitiveType.ELLIPSE)
             and not (p.text or "").startswith("container")]
    connectors = [p for p in primitives if p.ptype in (PrimitiveType.LINE, PrimitiveType.ARROW)]

    max_dim = max(img_size[0], img_size[1], 1)
    threshold = max(80, max_dim // 20)

    for conn in connectors:
        if len(conn.endpoints) < 2:
            continue

        ep1 = np.array(conn.endpoints[0])
        ep2 = np.array(conn.endpoints[1])

        nearest1 = find_nearest_shape(ep1, rects, threshold=threshold)
        nearest2 = find_nearest_shape(ep2, rects, threshold=threshold)

        if nearest1 is None and nearest2 is None:
            continue
        if nearest1 is not None and nearest2 is not None and nearest1 == nearest2:
            continue

        direction = "none"
        if conn.ptype == PrimitiveType.ARROW:
            if conn.arrowhead == "end":
                direction = "forward"
            elif conn.arrowhead == "start":
                direction = "backward"
            elif conn.arrowhead == "both":
                direction = "both"

        from_id = nearest1.id if nearest1 else -1
        to_id = nearest2.id if nearest2 else -1

        connections.append(Connection(
            from_id=from_id,
            to_id=to_id,
            connector_id=conn.id,
            direction=direction,
        ))

    return connections


def find_nearest_shape(point: np.ndarray, shapes: list, threshold=80) -> Optional[Primitive]:
    """Find the nearest rect/ellipse to a point.
    Uses distance to bbox edge, with point-inside-bbox counting as 0.
    """
    best = None
    best_dist = threshold

    for shape in shapes:
        if (shape.text or "").startswith("container"):
            continue
        bx, by, bw, bh = shape.bbox.x, shape.bbox.y, shape.bbox.w, shape.bbox.h
        # If point is inside bbox, distance is 0
        if bx <= point[0] <= bx + bw and by <= point[1] <= by + bh:
            dist = 0.0
        else:
            dx = max(bx - point[0], 0, point[0] - (bx + bw))
            dy = max(by - point[1], 0, point[1] - (by + bh))
            dist = math.hypot(dx, dy)
        if dist < best_dist:
            best_dist = dist
            best = shape

    return best


# ---------------------------------------------------------------------------
# 6. Generate TikZ
# ---------------------------------------------------------------------------

def generate_tikz(analysis: DiagramAnalysis, dpi=300) -> str:
    """Generate TikZ code from analysis results."""
    px_to_cm = 2.54 / dpi
    img_w, img_h = analysis.image_size

    # Normalize: find bounding box of all primitives, scale to ~12cm wide
    all_prims = [p for p in analysis.primitives
                 if p.ptype != PrimitiveType.UNKNOWN]
    if not all_prims:
        return "% No primitives detected"

    min_x = min(p.bbox.x for p in all_prims)
    min_y = min(p.bbox.y for p in all_prims)
    max_x = max(p.bbox.right for p in all_prims)
    max_y = max(p.bbox.bottom for p in all_prims)
    content_w = max(max_x - min_x, 1)
    content_h = max(max_y - min_y, 1)
    target_w = 14.0  # cm
    scale = target_w / content_w

    def tx(px_x):
        return round((px_x - min_x) * scale, 2)

    def ty(px_y):
        return round((max_y - px_y) * scale, 2)

    node_ids = set()
    lines = []
    lines.append("\\begin{tikzpicture}[")
    lines.append("  box/.style={draw, thick, minimum height=5mm, inner sep=2pt, font=\\small},")
    lines.append("  container/.style={draw, thick, rounded corners=1pt, inner sep=4pt},")
    lines.append("  lbl/.style={draw=none, inner sep=1pt, font=\\small},")
    lines.append("  arr/.style={-{Stealth[length=2.5mm]}, thick},")
    lines.append("]")

    # Containers first (behind other nodes)
    for p in analysis.primitives:
        if not (p.ptype == PrimitiveType.RECT and
                p.text and p.text.startswith("container")):
            continue
        x, y = tx(p.bbox.cx), ty(p.bbox.cy)
        w = round(p.bbox.w * scale, 2)
        h = round(p.bbox.h * scale, 2)
        label = p.text.replace("container:", "").replace("container", "").strip()
        lines.append(f"  \\node[container, minimum width={w}cm, minimum height={h}cm]"
                    f" (n{p.id}) at ({x},{y}) {{}};")
        if label:
            top_y = ty(p.bbox.y)
            lines.append(f"  \\node[lbl, anchor=south] at ({x},{top_y}) {{{label}}};")
        node_ids.add(p.id)

    # Regular shapes
    for p in analysis.primitives:
        if p.ptype == PrimitiveType.UNKNOWN:
            continue
        if p.ptype == PrimitiveType.RECT and p.text and p.text.startswith("container"):
            continue

        x, y = tx(p.bbox.cx), ty(p.bbox.cy)
        w = round(p.bbox.w * scale, 2)
        h = round(p.bbox.h * scale, 2)

        if p.ptype == PrimitiveType.RECT:
            label = p.text or ""
            lines.append(f"  \\node[box, minimum width={w}cm, minimum height={h}cm]"
                        f" (n{p.id}) at ({x},{y}) {{{label}}};")
            node_ids.add(p.id)

        elif p.ptype == PrimitiveType.ELLIPSE:
            label = p.text or ""
            lines.append(f"  \\node[box, ellipse] (n{p.id}) at ({x},{y}) {{{label}}};")
            node_ids.add(p.id)

        elif p.ptype in (PrimitiveType.LINE, PrimitiveType.ARROW):
            if p.endpoints and len(p.endpoints) == 2:
                ep1, ep2 = p.endpoints
                x1t, y1t = tx(ep1[0]), ty(ep1[1])
                x2t, y2t = tx(ep2[0]), ty(ep2[1])
                if p.ptype == PrimitiveType.ARROW:
                    ah = p.arrowhead or "end"
                    if ah == "both":
                        style = "{Stealth[length=2.5mm]}-{Stealth[length=2.5mm]}, thick"
                    elif ah == "start":
                        style = "{Stealth[length=2.5mm]}-, thick"
                    else:
                        style = "arr"
                    lines.append(f"  \\draw[{style}] ({x1t},{y1t}) -- ({x2t},{y2t});")
                else:
                    lines.append(f"  \\draw[thick] ({x1t},{y1t}) -- ({x2t},{y2t});")

        elif p.ptype == PrimitiveType.TEXT:
            if p.text:
                # Skip text that duplicates container title
                is_container_dup = False
                for cp in analysis.primitives:
                    if cp.ptype == PrimitiveType.RECT and (cp.text or "").startswith("container"):
                        clabel = cp.text.replace("container:", "").replace("container", "").strip()
                        if clabel and p.text in clabel:
                            is_container_dup = True
                            break
                if is_container_dup:
                    continue

                anchor = ""
                for rp in analysis.primitives:
                    if rp.ptype != PrimitiveType.RECT:
                        continue
                    if (rp.text or "").startswith("container"):
                        continue
                    dy = abs(p.bbox.cy - rp.bbox.cy)
                    if dy > rp.bbox.h:
                        continue
                    if p.bbox.x > rp.bbox.right and p.bbox.x - rp.bbox.right < 200:
                        anchor = ", anchor=west"
                        break
                    if p.bbox.right < rp.bbox.x and rp.bbox.x - p.bbox.right < 200:
                        anchor = ", anchor=east"
                        break
                lines.append(f"  \\node[lbl{anchor}] (t{p.id}) at ({x},{y}) {{{p.text}}};")

    lines.append("\\end{tikzpicture}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. Review items
# ---------------------------------------------------------------------------

def check_for_review(primitives: list, connections: list) -> list:
    """Identify items that need human/LLM review."""
    reviews = []

    # Low confidence primitives
    for p in primitives:
        if p.confidence < 0.5:
            reviews.append(ReviewItem(
                reason=ReviewReason.LOW_CONFIDENCE,
                primitive_id=p.id,
                description=f"Примитив {p.id} ({p.ptype.value}): уверенность {p.confidence:.0%}",
                crop_region=p.bbox,
            ))

    # Unclassified primitives
    unknowns = [p for p in primitives if p.ptype == PrimitiveType.UNKNOWN]
    for p in unknowns:
        reviews.append(ReviewItem(
            reason=ReviewReason.UNCLASSIFIED,
            primitive_id=p.id,
            description=f"Не удалось классифицировать примитив {p.id} (bbox: {p.bbox.w}x{p.bbox.h})",
            crop_region=p.bbox,
        ))

    # Lines without connections (possible missing arrows)
    connected_ids = set()
    for c in connections:
        connected_ids.add(c.connector_id)
    for p in primitives:
        if p.ptype in (PrimitiveType.LINE, PrimitiveType.ARROW) and p.id not in connected_ids:
            reviews.append(ReviewItem(
                reason=ReviewReason.ARROW_MISSING,
                primitive_id=p.id,
                description=f"Линия/стрелка {p.id} не соединяет никакие фигуры",
                crop_region=p.bbox,
            ))

    # Overlapping shapes
    rects = [p for p in primitives if p.ptype in (PrimitiveType.RECT, PrimitiveType.ELLIPSE)]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects[i].bbox.overlaps(rects[j].bbox, threshold=0.5):
                reviews.append(ReviewItem(
                    reason=ReviewReason.OVERLAP,
                    primitive_id=rects[i].id,
                    description=f"Фигуры {rects[i].id} и {rects[j].id} перекрываются",
                ))

    return reviews


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def analyze_figure(pdf_path: str, page_num: int, figure_num: str,
                   dpi=300, save_debug=False) -> DiagramAnalysis:
    """Run full analysis pipeline on a single figure."""
    print(f"  Анализ Figure {figure_num} (стр. {page_num})...")

    # 1. Crop
    img, crop_bbox, caption = crop_figure(pdf_path, page_num, figure_num, dpi)
    h, w = img.shape[:2]
    print(f"    Crop: {w}x{h} px")

    # 2. Classify
    img_class, class_conf = classify_image(img)
    print(f"    Класс: {img_class.value} ({class_conf:.0%})")

    # 3. Detect primitives
    primitives = detect_primitives(img)
    by_type = {}
    for p in primitives:
        by_type[p.ptype.value] = by_type.get(p.ptype.value, 0) + 1
    print(f"    Примитивы: {dict(by_type)}")

    # 4. OCR — fill text inside rects
    ocr_primitives(img, pdf_path, page_num, crop_bbox, primitives, dpi)
    labeled = sum(1 for p in primitives if p.text and p.text != "container")
    print(f"    С текстом: {labeled}")

    # 4b. Post-process OCR: fix common errors, remove garbage
    postprocess_ocr(primitives)

    # 4c. Associate text primitives with nearest shapes
    associate_text_to_shapes(primitives)

    # 5. Build topology
    connections = build_topology(primitives, (w, h))
    print(f"    Соединения: {len(connections)}")

    # 7. Check for review
    reviews = check_for_review(primitives, connections)
    if reviews:
        print(f"    ⚠ Требует проверки: {len(reviews)} элементов")

    analysis = DiagramAnalysis(
        figure_number=figure_num,
        page=page_num,
        image_class=img_class,
        classification_confidence=class_conf,
        primitives=primitives,
        connections=connections,
        reviews=[],
        image_size=(w, h),
        crop_bbox=crop_bbox,
    )
    analysis.reviews = reviews

    if save_debug:
        debug_dir = "debug_diagrams"
        os.makedirs(debug_dir, exist_ok=True)
        # Save crop
        cv2.imwrite(f"{debug_dir}/fig_{figure_num.replace('.', '_')}_crop.png", img)
        # Save annotated
        annotated = draw_annotations(img, primitives, connections)
        cv2.imwrite(f"{debug_dir}/fig_{figure_num.replace('.', '_')}_annotated.png", annotated)
        # Save analysis JSON
        with open(f"{debug_dir}/fig_{figure_num.replace('.', '_')}_analysis.json", "w") as f:
            json.dump(analysis.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        print(f"    Debug → {debug_dir}/")

    return analysis


def draw_annotations(img: np.ndarray, primitives: list, connections: list) -> np.ndarray:
    """Draw detected primitives on image for debugging."""
    annotated = img.copy()
    colors = {
        PrimitiveType.RECT: (0, 255, 0),      # green
        PrimitiveType.LINE: (255, 0, 0),       # blue
        PrimitiveType.ARROW: (0, 0, 255),      # red
        PrimitiveType.TEXT: (255, 255, 0),      # cyan
        PrimitiveType.ELLIPSE: (255, 0, 255),   # magenta
        PrimitiveType.UNKNOWN: (128, 128, 128),  # gray
    }

    for p in primitives:
        color = colors.get(p.ptype, (128, 128, 128))
        cv2.rectangle(annotated,
                      (p.bbox.x, p.bbox.y),
                      (p.bbox.right, p.bbox.bottom),
                      color, 2)
        label = f"{p.id}:{p.ptype.value[:3]}"
        cv2.putText(annotated, label, (p.bbox.x, p.bbox.y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # Draw endpoints for lines/arrows
        for ep in p.endpoints:
            cv2.circle(annotated, ep, 5, (0, 0, 255), -1)

    return annotated


def analyze_chapter(pdf_path: str, chapter: int, start: int, end: int,
                    manifest_path: str = None, save_debug=False):
    """Analyze all figures in a chapter."""
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        figures = manifest.get("figures", [])
    else:
        # Fall back to scanning PDF
        doc = fitz.open(pdf_path)
        figures = []
        for i in range(start, end + 1):
            if i >= len(doc):
                break
            text = doc[i].get_text()
            for m in re.finditer(r'Figure\s+(\d+\.\d+)', text):
                figures.append({"page": i, "number": m.group(1), "type": "unknown"})
        doc.close()

    # Filter to diagrams only (skip debug_session, source_listing)
    diagram_figs = [f for f in figures if f.get("type") not in ("debug_session", "source_listing")]

    print(f"{'='*60}")
    print(f"DIAGRAM ANALYSIS: Глава {chapter} ({len(diagram_figs)} фигур)")
    print(f"{'='*60}")

    results = []
    for fig in diagram_figs:
        analysis = analyze_figure(pdf_path, fig["page"], fig["number"], save_debug=save_debug)
        results.append(analysis)

    # Summary
    total_prims = sum(len(a.primitives) for a in results)
    total_reviews = sum(len(a.reviews) for a in results)
    diagrams = sum(1 for a in results if a.image_class == ImageClass.DIAGRAM)

    print(f"\n{'='*60}")
    print(f"ИТОГО:")
    print(f"  Фигур: {len(results)}")
    print(f"  Диаграмм: {diagrams}")
    print(f"  Примитивов: {total_prims}")
    print(f"  Требуют проверки: {total_reviews}")

    # Save results
    output_file = f"ch{chapter}_diagrams.json"
    with open(output_file, "w") as f:
        json.dump([a.to_dict() for a in results], f, ensure_ascii=False, indent=2, default=str)
    print(f"  Результат: {output_file}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Diagram extraction and analysis")
    parser.add_argument("--input", "-i", default="80888086micropro0000trie_2.pdf")
    parser.add_argument("--chapter", "-c", type=int)
    parser.add_argument("--start", "-s", type=int)
    parser.add_argument("--end", "-e", type=int)
    parser.add_argument("--page", "-p", type=int, help="Single page")
    parser.add_argument("--figure", "-f", help="Single figure number (e.g. 4.10)")
    parser.add_argument("--manifest", "-m", help="Chapter manifest JSON")
    parser.add_argument("--debug", "-d", action="store_true", help="Save debug images")
    args = parser.parse_args()

    if args.page and args.figure:
        analysis = analyze_figure(args.input, args.page, args.figure, save_debug=args.debug)
        print(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2, default=str))
    elif args.chapter and args.start and args.end:
        manifest = args.manifest or f"ch{args.chapter}_manifest.json"
        analyze_chapter(args.input, args.chapter, args.start, args.end,
                       manifest, save_debug=args.debug)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
