"""PDF text extraction with structural analysis.

Uses PyMuPDF get_text('dict') to extract blocks with font metadata,
classifies them (heading hierarchy/body/code/caption/list/footnote),
detects columns, tables, headers/footers, and assembles clean Markdown.
"""

import hashlib
import json
import logging
import os
import re
from collections import Counter

import fitz

log = logging.getLogger("bookassembler")

# Trailing words that signal a line continues on the next line, per language.
_CONTINUATION_WORDS = {
    "en": (
        r"the|a|an|of|in|to|for|and|or|is|are|by|on|with|from|that|which|as|"
        r"but|not|if|at|be|has|have|this|than|may|can|also|when|each|into|"
        r"between|all|more|both|they|their|these|it|such|its|was|were|been"
    ),
    "ru": (
        r"и|в|на|с|по|к|из|за|о|у|от|для|до|не|что|как|это|но|а|или|"
        r"при|его|её|их|он|она|мы|вы|все|так|уже|ещё|бы|же|ли|между"
    ),
    "de": (
        r"der|die|das|und|in|von|zu|mit|auf|für|an|ist|den|dem|ein|eine|"
        r"als|auch|es|des|sich|nicht|werden|bei|nach|aus|über|durch"
    ),
    "fr": (
        r"le|la|les|de|du|des|un|une|et|en|à|dans|pour|par|sur|avec|"
        r"est|sont|qui|que|ce|cette|il|elle|nous|vous|ils|pas|plus"
    ),
    "es": (
        r"el|la|los|las|de|del|un|una|y|en|por|para|con|que|es|"
        r"son|se|al|como|su|sus|más|pero|no|todo|esta|este"
    ),
}


def _get_continuation_pattern(lang: str) -> re.Pattern | None:
    words = _CONTINUATION_WORDS.get(lang)
    if not words:
        return None
    return re.compile(rf"\b({words})\s*$", re.IGNORECASE)


class BookExtractor:
    """Extracts and cleans text from PDF pages."""

    def __init__(self, pdf_path: str, cache_dir: str = "cache/text",
                 images_dir: str = "cache/images", source_lang: str = "en"):
        self.pdf_path = pdf_path
        self.cache_dir = cache_dir
        self.images_dir = images_dir
        self.source_lang = source_lang
        self._continuation_re = _get_continuation_pattern(source_lang)

    def extract(self, start: int, end: int) -> str:
        """Extract pages [start, end] to JSON cache. Returns cache file path."""
        cache_file = os.path.join(self.cache_dir, f"pages_{start}_{end}.json")
        hash_file = os.path.join(self.cache_dir, f"pages_{start}_{end}.pdfhash")

        if os.path.exists(cache_file):
            current_hash = self._pdf_hash()
            cached_hash = ""
            if os.path.exists(hash_file):
                cached_hash = open(hash_file).read().strip()
            if current_hash == cached_hash:
                log.info("cached: %s", cache_file)
                return cache_file
            else:
                log.warning("PDF изменился, перечитываю (old=%s new=%s)",
                            cached_hash[:8], current_hash[:8])

        os.makedirs(self.cache_dir, exist_ok=True)
        doc = fitz.open(self.pdf_path)

        # Extract TOC if available
        toc = doc.get_toc(simple=True)
        toc_map: dict[int, list[tuple[int, str]]] = {}
        for level, title, page_num in toc:
            pg = page_num - 1
            toc_map.setdefault(pg, []).append((level, title))
        if toc:
            log.info("TOC: %d записей из PDF bookmarks", len(toc))

        # Pass 1: extract blocks + save images with bbox matching
        page_blocks: dict[str, list[dict]] = {}
        all_blocks: list[dict] = []
        img_dir = os.path.join(self.images_dir, f"pages_{start}_{end}")
        os.makedirs(img_dir, exist_ok=True)
        img_count = 0

        for i in range(start, end + 1):
            if i >= len(doc):
                break
            page = doc[i]
            blocks = self._extract_page_blocks(page)

            # OCR fallback: if no text extracted, try OCR
            text_blocks = [b for b in blocks if b["block_type"] == "text"]
            if not text_blocks:
                ocr_text = self._ocr_page(page)
                if ocr_text:
                    blocks.append({
                        "text": ocr_text,
                        "x0": 0, "y0": 0,
                        "x1": page.rect.width, "y1": page.rect.height,
                        "font_size": 0, "is_bold": False, "is_mono": False,
                        "block_type": "text",
                        "page_height": page.rect.height,
                        "page_width": page.rect.width,
                    })
                    log.debug("OCR fallback for page %d", i)

            # Save images with proper bbox matching
            img_count += self._save_page_images(doc, page, i, blocks, img_dir)

            # Store TOC entries for this page
            if i in toc_map:
                for b in blocks:
                    b["_toc_entries"] = toc_map[i]

            page_blocks[str(i)] = blocks
            all_blocks.extend(blocks)

        doc.close()
        if img_count:
            log.info("Сохранено %d изображений -> %s", img_count, img_dir)

        # Pass 2: global analysis
        body_size = self._detect_body_font_size(all_blocks)
        if body_size:
            log.info("Размер основного шрифта: %d pt", body_size)

        heading_levels = self._build_heading_hierarchy(all_blocks, body_size)
        hf_texts, hf_patterns = self._detect_headers_footers(all_blocks, len(page_blocks))
        if hf_texts or hf_patterns:
            log.info("Колонтитулы: %d точных, %d паттернов", len(hf_texts), len(hf_patterns))

        # Pass 3: build clean text per page
        texts = {}
        for pg, blocks in page_blocks.items():
            texts[pg] = self._build_page_text(
                blocks, body_size, heading_levels, hf_texts, hf_patterns,
            )

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(texts, f, ensure_ascii=False, indent=2)

        with open(hash_file, "w") as f:
            f.write(self._pdf_hash())

        log.info("Извлечено %d страниц -> %s", len(texts), cache_file)
        return cache_file

    # ------------------------------------------------------------------
    # PDF hashing
    # ------------------------------------------------------------------

    def _pdf_hash(self, chunk_size: int = 65536) -> str:
        h = hashlib.md5()
        with open(self.pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    # ------------------------------------------------------------------
    # OCR fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _ocr_page(page) -> str:
        """Try OCR on a page with no extractable text."""
        try:
            tp = page.get_textpage_ocr(language="eng", dpi=300)
            text = page.get_text("text", textpage=tp).strip()
            return text if len(text) > 20 else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Image extraction with bbox matching
    # ------------------------------------------------------------------

    @staticmethod
    def _save_page_images(doc, page, page_num: int,
                          blocks: list[dict], img_dir: str) -> int:
        """Save images and match them to image blocks by bbox overlap."""
        saved = 0
        image_blocks = [b for b in blocks if b["block_type"] == "image"]

        for j, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                if pix.width < 50 or pix.height < 50:
                    continue

                fname = f"page_{page_num}_img_{j}.png"
                pix.save(os.path.join(img_dir, fname))
                saved += 1

                # Match by bbox overlap using get_image_rects
                rects = page.get_image_rects(xref)
                if rects:
                    img_rect = rects[0]
                    best_block = None
                    best_overlap = 0
                    for b in image_blocks:
                        if b.get("image_file"):
                            continue
                        block_rect = fitz.Rect(b["x0"], b["y0"], b["x1"], b["y1"])
                        overlap = abs(block_rect & img_rect)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_block = b
                    if best_block:
                        best_block["image_file"] = fname
                else:
                    # Fallback: assign to first unmatched image block
                    for b in image_blocks:
                        if not b.get("image_file"):
                            b["image_file"] = fname
                            break
            except Exception:
                pass
        return saved

    # ------------------------------------------------------------------
    # Block extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_page_blocks(page) -> list[dict]:
        """Extract structured blocks from a PDF page using get_text('dict')."""
        data = page.get_text("dict")
        page_height = data["height"]
        page_width = data["width"]
        results = []

        for block in data["blocks"]:
            if block["type"] == 1:
                results.append({
                    "text": "",
                    "x0": block["bbox"][0], "y0": block["bbox"][1],
                    "x1": block["bbox"][2], "y1": block["bbox"][3],
                    "font_size": 0, "is_bold": False, "is_mono": False,
                    "block_type": "image",
                })
                continue

            lines_text = []
            sizes = []
            bold_count = 0
            mono_count = 0
            span_count = 0

            for line in block["lines"]:
                spans_text = []
                for span in line["spans"]:
                    spans_text.append(span["text"])
                    if span["text"].strip():
                        sizes.append(span["size"])
                        span_count += 1
                        if span["flags"] & 16:
                            bold_count += 1
                        if span["flags"] & 8:
                            mono_count += 1
                lines_text.append("".join(spans_text))

            text = "\n".join(lines_text)
            if not text.strip():
                continue

            avg_size = sum(sizes) / len(sizes) if sizes else 0
            results.append({
                "text": text,
                "x0": block["bbox"][0], "y0": block["bbox"][1],
                "x1": block["bbox"][2], "y1": block["bbox"][3],
                "font_size": avg_size,
                "is_bold": bold_count > span_count / 2 if span_count else False,
                "is_mono": mono_count > span_count / 2 if span_count else False,
                "block_type": "text",
                "page_height": page_height,
                "page_width": page_width,
            })

        return results

    # ------------------------------------------------------------------
    # Column detection (clustering-based)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_columns(blocks: list[dict]) -> int:
        """Detect column count using x0 clustering.

        Groups block x0 values into clusters (tolerance = 5% of page width).
        Two clusters with enough blocks = two columns.
        Ignores wide blocks (tables, figures) that span the full page.
        """
        text_blocks = [b for b in blocks if b["block_type"] == "text"
                       and len(b["text"].strip()) > 30]
        if len(text_blocks) < 4:
            return 1

        page_w = text_blocks[0].get("page_width", 0)
        if not page_w:
            return 1

        # Filter out wide blocks (> 60% of page width)
        narrow = [b for b in text_blocks if (b["x1"] - b["x0"]) < page_w * 0.6]
        if len(narrow) < 4:
            return 1

        # Cluster x0 values
        tolerance = page_w * 0.05
        x0s = sorted(b["x0"] for b in narrow)
        clusters: list[list[float]] = []
        for x in x0s:
            placed = False
            for cluster in clusters:
                if abs(x - cluster[0]) < tolerance:
                    cluster.append(x)
                    placed = True
                    break
            if not placed:
                clusters.append([x])

        # Need at least 2 clusters with 3+ blocks each
        significant = [c for c in clusters if len(c) >= 3]
        if len(significant) >= 2:
            centers = sorted(sum(c) / len(c) for c in significant)
            # Check there's a real gap between clusters (> 20% of page width)
            if len(centers) >= 2 and (centers[1] - centers[0]) > page_w * 0.2:
                return 2

        return 1

    @staticmethod
    def _sort_blocks_by_columns(blocks: list[dict], num_columns: int) -> list[dict]:
        """Sort blocks in reading order: column by column, top to bottom."""
        if num_columns <= 1:
            return sorted(blocks, key=lambda b: (b["y0"], b["x0"]))

        page_w = blocks[0].get("page_width", 0) if blocks else 0
        mid = page_w / 2 if page_w else 0

        # Wide blocks (>60% page width) go between columns at their y position
        wide = []
        left = []
        right = []
        for b in blocks:
            width = b["x1"] - b["x0"]
            if width > page_w * 0.6:
                wide.append(b)
            elif b["x0"] + width / 2 < mid:
                left.append(b)
            else:
                right.append(b)

        left.sort(key=lambda b: b["y0"])
        right.sort(key=lambda b: b["y0"])
        wide.sort(key=lambda b: b["y0"])

        # Interleave: wide blocks split the column flow
        result = []
        li = ri = wi = 0
        while li < len(left) or ri < len(right) or wi < len(wide):
            next_wide_y = wide[wi]["y0"] if wi < len(wide) else float("inf")

            # Add left-column blocks before the next wide block
            while li < len(left) and left[li]["y0"] < next_wide_y:
                result.append(left[li])
                li += 1
            # Add right-column blocks before the next wide block
            while ri < len(right) and right[ri]["y0"] < next_wide_y:
                result.append(right[ri])
                ri += 1
            # Add wide block
            if wi < len(wide):
                result.append(wide[wi])
                wi += 1

        return result

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_body_font_size(all_blocks: list[dict]) -> float:
        """Find the most common font size across all pages — this is body text."""
        size_counts: Counter = Counter()
        for b in all_blocks:
            if b["block_type"] != "text":
                continue
            char_count = len(b["text"].strip())
            size_counts[round(b["font_size"])] += char_count
        if not size_counts:
            return 0
        return size_counts.most_common(1)[0][0]

    @staticmethod
    def _build_heading_hierarchy(all_blocks: list[dict],
                                 body_size: float) -> dict[int, int]:
        """Map rounded font sizes to heading levels (#, ##, ###, ####).

        Returns {rounded_size: md_level} for sizes larger than body.
        """
        if not body_size:
            return {}

        heading_sizes: Counter = Counter()
        for b in all_blocks:
            if b["block_type"] != "text":
                continue
            size = round(b["font_size"])
            if size > body_size * 1.1:
                heading_sizes[size] += 1

        if not heading_sizes:
            return {}

        # Sort descending: largest font = level 1
        sorted_sizes = sorted(heading_sizes.keys(), reverse=True)
        levels = {}
        for i, size in enumerate(sorted_sizes):
            levels[size] = min(i + 1, 6)  # cap at h6

        return levels

    @staticmethod
    def _detect_headers_footers(all_blocks: list[dict],
                                page_count: int) -> tuple[set[str], list[re.Pattern]]:
        """Detect repeating header/footer text and patterns across pages."""
        if page_count < 3:
            return set(), []

        top_texts: Counter = Counter()
        bottom_texts: Counter = Counter()

        for b in all_blocks:
            if b["block_type"] != "text":
                continue
            text = b["text"].strip()
            if not text or len(text) > 80:
                continue
            page_h = b.get("page_height", 0)
            if not page_h:
                continue

            rel_y = b["y0"] / page_h
            if rel_y < 0.12:
                top_texts[text] += 1
            elif rel_y > 0.88:
                bottom_texts[text] += 1

        threshold = max(3, page_count * 0.3)
        hf_texts = set()

        for text, count in list(top_texts.items()) + list(bottom_texts.items()):
            if count >= threshold and not re.match(r"^[a-z]{1,4}$", text, re.IGNORECASE):
                hf_texts.add(text)

        hf_patterns = []
        _CANDIDATE_PATTERNS = [
            r"^Sec\.\s+\d",
            r"^Chap\.\s+\d",
            r"^Chapter\s+\d",
            r"^Section\s+\d",
            r"^Глава\s+\d",
            r"^Раздел\s+\d",
        ]
        for pat_str in _CANDIDATE_PATTERNS:
            pat = re.compile(pat_str, re.IGNORECASE)
            match_count = sum(1 for t in list(top_texts) + list(bottom_texts)
                              if pat.search(t))
            if match_count >= threshold:
                hf_patterns.append(pat)

        return hf_texts, hf_patterns

    # ------------------------------------------------------------------
    # Table detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_table(blocks: list[dict], start_idx: int) -> list[dict] | None:
        """Detect a table starting at start_idx.

        Looks for consecutive blocks at similar y-positions (same row)
        or blocks with aligned x-coordinates (columns).
        Returns list of blocks forming the table, or None.
        """
        if start_idx >= len(blocks):
            return None

        candidates = blocks[start_idx:]
        if len(candidates) < 4:
            return None

        # Strategy: find blocks sharing similar x0 values (column alignment)
        page_h = candidates[0].get("page_height", 0)
        if not page_h:
            return None

        # Collect x0 positions of consecutive short text blocks
        aligned_blocks = []
        x_positions: list[set[int]] = []

        for b in candidates:
            if b["block_type"] != "text":
                break
            text = b["text"].strip()
            if not text:
                continue
            # Table cells are usually short
            lines = text.split("\n")
            if any(len(line) > 80 for line in lines):
                break
            aligned_blocks.append(b)

        if len(aligned_blocks) < 4:
            return None

        # Check if x0 values cluster into columns
        tolerance = 20
        x0_values = [round(b["x0"]) for b in aligned_blocks]
        x0_clusters: Counter = Counter()
        for x in x0_values:
            # Round to nearest tolerance
            rounded = round(x / tolerance) * tolerance
            x0_clusters[rounded] += 1

        # Need at least 2 "columns" with 2+ blocks each
        col_count = sum(1 for c in x0_clusters.values() if c >= 2)
        if col_count >= 2:
            return aligned_blocks

        return None

    @staticmethod
    def _blocks_to_markdown_table(blocks: list[dict]) -> str:
        """Convert aligned blocks into a Markdown table."""
        if not blocks:
            return ""

        tolerance = 20

        # Group blocks by y-coordinate (rows)
        rows: list[list[dict]] = []
        current_row: list[dict] = [blocks[0]]
        for b in blocks[1:]:
            if abs(b["y0"] - current_row[0]["y0"]) < tolerance:
                current_row.append(b)
            else:
                rows.append(sorted(current_row, key=lambda x: x["x0"]))
                current_row = [b]
        rows.append(sorted(current_row, key=lambda x: x["x0"]))

        if len(rows) < 2:
            return ""

        # Determine number of columns from the widest row
        num_cols = max(len(row) for row in rows)

        lines = []
        for i, row in enumerate(rows):
            cells = [b["text"].strip().replace("\n", " ").replace("|", "\\|")
                     for b in row]
            # Pad if needed
            while len(cells) < num_cols:
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in range(num_cols)) + " |")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # List detection
    # ------------------------------------------------------------------

    _LIST_BULLET_RE = re.compile(
        r"^(?:[•‣◦⁃∙•·\-\*]"  # bullet chars
        r"|[a-z]\)"                                       # a) b) c)
        r"|\d{1,3}[\.\)]"                                # 1. 2) 3.
        r")\s+",
        re.IGNORECASE,
    )

    @classmethod
    def _detect_list_item(cls, text: str) -> tuple[str, str] | None:
        """Detect if text starts with a list marker.
        Returns (marker, content) or None.
        """
        m = cls._LIST_BULLET_RE.match(text)
        if m:
            return m.group().strip(), text[m.end():]
        return None

    # ------------------------------------------------------------------
    # Footnote detection
    # ------------------------------------------------------------------

    _FOOTNOTE_REF_RE = re.compile(r"(\w)([¹²³⁴⁵⁶⁷⁸⁹⁰]+|\^(\d+))")
    _FOOTNOTE_DEF_RE = re.compile(r"^(\d+)\s+(.+)", re.MULTILINE)

    # ------------------------------------------------------------------
    # Caption-image association
    # ------------------------------------------------------------------

    _CAPTION_RE = re.compile(
        r"^(Figure|Fig\.|Table|Example|FIGURE|TABLE|EXAMPLE|"
        r"Рис\.|Рисунок|Таблица|Пример)\s+[\d]",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # Block classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_block(block: dict, body_size: float,
                        heading_levels: dict[int, int]) -> str:
        """Classify a text block with heading hierarchy."""
        text = block["text"].strip()

        if re.match(r"^\d{1,4}$", text):
            return "page_number"

        if block["is_mono"]:
            return "code"

        if body_size > 0:
            rounded = round(block["font_size"])
            if rounded in heading_levels:
                return f"heading_{heading_levels[rounded]}"

        if re.match(
            r"^(Figure|Fig\.|Table|Example|FIGURE|TABLE|EXAMPLE|"
            r"Рис\.|Рисунок|Таблица|Пример)\s+\d",
            text, re.IGNORECASE,
        ):
            return "caption"

        return "body"

    # ------------------------------------------------------------------
    # Cross-references
    # ------------------------------------------------------------------

    _XREF_RE = re.compile(
        r"((?:Figure|Fig\.|Table|Example|Рис\.|Рисунок|Таблица|Пример)"
        r"\s+(\d+[\-\.]\d+|\d+))",
        re.IGNORECASE,
    )

    @classmethod
    def _add_cross_references(cls, text: str) -> str:
        """Convert 'Figure 12' to '[Figure 12](#figure-12)'."""
        def _repl(m):
            full = m.group(1)
            anchor = re.sub(r"[^a-z0-9]+", "-", full.lower()).strip("-")
            return f"[{full}](#{anchor})"
        return cls._XREF_RE.sub(_repl, text)

    # ------------------------------------------------------------------
    # Page text assembly
    # ------------------------------------------------------------------

    @classmethod
    def _build_page_text(cls, blocks: list[dict], body_size: float,
                         heading_levels: dict[int, int],
                         hf_texts: set[str],
                         hf_patterns: list[re.Pattern] | None = None) -> str:
        """Build clean Markdown text from structured blocks."""
        # Sort blocks in reading order (handles multi-column layouts)
        num_cols = cls._detect_columns(blocks)
        blocks = cls._sort_blocks_by_columns(blocks, num_cols)

        # Insert TOC headings if available
        toc_entries = None
        for b in blocks:
            if "_toc_entries" in b:
                toc_entries = b["_toc_entries"]
                break

        parts: list[str] = []

        if toc_entries:
            for level, title in toc_entries:
                hashes = "#" * min(level, 6)
                parts.append(f"\n{hashes} {title}\n")

        # Track previous block for caption-image association
        prev_was_image = False
        skip_table_blocks: set[int] = set()
        i = 0

        while i < len(blocks):
            b = blocks[i]
            block_id = id(b)

            if block_id in skip_table_blocks:
                i += 1
                continue

            # --- Images ---
            if b["block_type"] == "image":
                img_file = b.get("image_file")
                if img_file:
                    parts.append(f"\n![image]({img_file})\n")
                    prev_was_image = True
                i += 1
                continue

            text = b["text"].strip()
            if not text:
                i += 1
                continue

            # --- Header/footer removal ---
            if text in hf_texts:
                i += 1
                continue

            page_h = b.get("page_height", 0)
            if page_h:
                rel_y = b["y0"] / page_h
                in_margin = rel_y < 0.10 or rel_y > 0.90
                if in_margin:
                    if hf_patterns and any(p.search(text) for p in hf_patterns):
                        i += 1
                        continue
                    if re.match(r"^\d{1,4}$", text):
                        i += 1
                        continue
                    if len(text) < 80 and re.search(
                            r"(Sec\.|Chap\.|Chapter|Section|Глава|Раздел)\s*\d",
                            text, re.IGNORECASE):
                        i += 1
                        continue

            btype = cls._classify_block(b, body_size, heading_levels)

            if btype == "page_number":
                i += 1
                continue

            # --- Caption after image → associate ---
            if btype == "caption" and prev_was_image:
                anchor = re.sub(r"[^a-z0-9]+", "-", text.split("\n")[0].lower()).strip("-")
                parts.append(f'\n**{text}** {{#{anchor}}}\n')
                prev_was_image = False
                i += 1
                continue

            # --- Caption before image → also associate ---
            if btype == "caption":
                anchor = re.sub(r"[^a-z0-9]+", "-", text.split("\n")[0].lower()).strip("-")
                parts.append(f'\n**{text}** {{#{anchor}}}\n')
                i += 1
                continue

            prev_was_image = False

            # --- Headings with hierarchy ---
            if btype.startswith("heading_"):
                level = int(btype.split("_")[1])
                hashes = "#" * level
                parts.append(f"\n{hashes} {text}\n")
                i += 1
                continue

            # --- Code ---
            if btype == "code":
                parts.append(f"\n```\n{text}\n```\n")
                i += 1
                continue

            # --- Table detection ---
            table_blocks = cls._detect_table(blocks, i)
            if table_blocks:
                md_table = cls._blocks_to_markdown_table(table_blocks)
                if md_table:
                    parts.append(f"\n{md_table}\n")
                    for tb in table_blocks:
                        skip_table_blocks.add(id(tb))
                    i += len(table_blocks)
                    continue

            # --- List detection ---
            list_item = cls._detect_list_item(text)
            if list_item:
                marker, content = list_item
                if re.match(r"\d+[\.\)]", marker):
                    parts.append(f"1. {content}")
                else:
                    parts.append(f"- {content}")
                i += 1
                continue

            # --- Footnote detection (bottom of page) ---
            if page_h and b["y0"] / page_h > 0.85:
                fn_match = cls._FOOTNOTE_DEF_RE.match(text)
                if fn_match:
                    fn_num = fn_match.group(1)
                    fn_text = fn_match.group(2)
                    parts.append(f"\n[^{fn_num}]: {fn_text}\n")
                    i += 1
                    continue

            # --- Regular body text ---
            parts.append(text)
            i += 1

        raw = "\n".join(parts)

        # Fix hyphenated word breaks: "proc-\nessing" → "processing"
        raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)

        # Fix dangling punctuation
        raw = re.sub(r"\n([,;:])", r" \1", raw)

        # Add cross-references
        raw = cls._add_cross_references(raw)

        # Join broken lines within paragraphs (not inside code/table blocks)
        raw = cls._join_lines(raw, cls._continuation_re_default)

        # Collapse multiple blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)

        return raw.strip()

    # Default continuation pattern (English)
    _continuation_re_default = _get_continuation_pattern("en")

    @staticmethod
    def _join_lines(raw: str, continuation_re: re.Pattern | None) -> str:
        """Join broken lines within paragraphs, preserving code/tables."""
        sections = re.split(r"(```.*?```)", raw, flags=re.DOTALL)
        result_parts = []

        for section in sections:
            if section.startswith("```"):
                result_parts.append(section)
                continue

            lines = section.split("\n")
            merged = []
            j = 0
            while j < len(lines):
                line = lines[j]
                while (j + 1 < len(lines)
                       and line.rstrip()
                       and not line.strip().startswith("#")
                       and not line.strip().startswith("**")
                       and not line.strip().startswith("- ")
                       and not line.strip().startswith("1. ")
                       and not line.strip().startswith("|")
                       and not line.strip().startswith("[^")
                       and lines[j + 1].strip()
                       and not lines[j + 1].strip().startswith("#")
                       and not lines[j + 1].strip().startswith("**")
                       and not lines[j + 1].strip().startswith("- ")
                       and not lines[j + 1].strip().startswith("1. ")
                       and not lines[j + 1].strip().startswith("|")
                       and not lines[j + 1].strip().startswith("![")
                       and not lines[j + 1].strip().startswith("[^")
                       and (re.match(r"^[a-zа-яё,;(]", lines[j + 1].strip())
                            or re.search(r"[,;]\s*$", line.rstrip())
                            or (continuation_re
                                and continuation_re.search(line.rstrip())))):
                    next_line = lines[j + 1].strip()
                    line = line.rstrip() + " " + next_line
                    j += 1
                merged.append(line)
                j += 1
            result_parts.append("\n".join(merged))

        return "".join(result_parts)
