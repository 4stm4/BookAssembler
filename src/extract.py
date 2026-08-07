"""PDF text extraction with structural analysis.

Uses PyMuPDF get_text('dict') to extract blocks with font metadata,
then classifies them (heading/body/code/caption), detects and removes
headers/footers, and joins broken lines.
"""

import hashlib
import json
import logging
import os
import re
from collections import Counter

import fitz

log = logging.getLogger("bookassembler")


class BookExtractor:
    """Extracts and cleans text from PDF pages."""

    def __init__(self, pdf_path: str, cache_dir: str = "cache/text",
                 images_dir: str = "cache/images"):
        self.pdf_path = pdf_path
        self.cache_dir = cache_dir
        self.images_dir = images_dir

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

        # Pass 1: extract all blocks with metadata + save images
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
            # Save embedded images
            for j, img_info in enumerate(page.get_images(full=True)):
                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.width >= 50 and pix.height >= 50:
                        fname = f"page_{i}_img_{j}.png"
                        pix.save(os.path.join(img_dir, fname))
                        img_count += 1
                        for b in blocks:
                            if b["block_type"] == "image":
                                b["image_file"] = fname
                                break
                except Exception:
                    pass
            page_blocks[str(i)] = blocks
            all_blocks.extend(blocks)
        doc.close()
        if img_count:
            log.info("Сохранено %d изображений -> %s", img_count, img_dir)

        # Pass 2: detect body font size and header/footer patterns
        body_size = self._detect_body_font_size(all_blocks)
        if body_size:
            log.info("Размер основного шрифта: %d pt", body_size)

        hf_texts, hf_patterns = self._detect_headers_footers(all_blocks, len(page_blocks))
        if hf_texts or hf_patterns:
            log.info("Колонтитулы: %d точных, %d паттернов", len(hf_texts), len(hf_patterns))

        # Pass 3: build clean text per page
        texts = {}
        for pg, blocks in page_blocks.items():
            texts[pg] = self._build_page_text(blocks, body_size, hf_texts, hf_patterns)

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
    # Column detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_columns(blocks: list[dict]) -> int:
        """Detect if the page uses a multi-column layout.

        Returns the number of columns (1 or 2). Looks for a bimodal
        distribution of block x-starts with a clear gap in the middle.
        """
        text_blocks = [b for b in blocks if b["block_type"] == "text"
                       and len(b["text"].strip()) > 20]
        if len(text_blocks) < 4:
            return 1

        page_w = text_blocks[0].get("page_width", 0)
        if not page_w:
            return 1

        mid = page_w / 2
        left = [b for b in text_blocks if b["x1"] < mid * 1.1]
        right = [b for b in text_blocks if b["x0"] > mid * 0.9]

        if len(left) >= 3 and len(right) >= 3:
            return 2
        return 1

    @staticmethod
    def _sort_blocks_by_columns(blocks: list[dict], num_columns: int) -> list[dict]:
        """Sort blocks in reading order: column by column, top to bottom."""
        if num_columns <= 1:
            return sorted(blocks, key=lambda b: (b["y0"], b["x0"]))

        page_w = blocks[0].get("page_width", 0) if blocks else 0
        mid = page_w / 2 if page_w else 0

        left = sorted([b for b in blocks if b["x0"] < mid], key=lambda b: b["y0"])
        right = sorted([b for b in blocks if b["x0"] >= mid], key=lambda b: b["y0"])
        return left + right

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
    def _detect_headers_footers(all_blocks: list[dict],
                                page_count: int) -> tuple[set[str], list[re.Pattern]]:
        """Detect repeating header/footer text and patterns across pages.

        Uses block position (top/bottom 12% of page) and repetition.
        Returns (exact_texts_to_remove, regex_patterns_to_remove).
        """
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
        ]
        for pat_str in _CANDIDATE_PATTERNS:
            pat = re.compile(pat_str, re.IGNORECASE)
            match_count = sum(1 for t in list(top_texts) + list(bottom_texts)
                              if pat.search(t))
            if match_count >= threshold:
                hf_patterns.append(pat)

        return hf_texts, hf_patterns

    # ------------------------------------------------------------------
    # Block classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_block(block: dict, body_size: float) -> str:
        """Classify a text block: heading, body, code, caption, page_number."""
        text = block["text"].strip()

        if re.match(r"^\d{1,4}$", text):
            return "page_number"

        if block["is_mono"]:
            return "code"

        if body_size > 0:
            ratio = block["font_size"] / body_size
            if ratio > 1.15:
                return "heading"

        if re.match(r"^(Figure|Fig\.|Table|Example|FIGURE|TABLE|EXAMPLE)\s+\d", text):
            return "caption"

        return "body"

    # ------------------------------------------------------------------
    # Page text assembly
    # ------------------------------------------------------------------

    @classmethod
    def _build_page_text(cls, blocks: list[dict], body_size: float,
                         hf_texts: set[str],
                         hf_patterns: list[re.Pattern] | None = None) -> str:
        """Build clean text from structured blocks for a single page."""
        # Sort blocks in reading order (handles multi-column layouts)
        num_cols = cls._detect_columns(blocks)
        blocks = cls._sort_blocks_by_columns(blocks, num_cols)

        parts = []

        for b in blocks:
            if b["block_type"] == "image":
                img_file = b.get("image_file")
                if img_file:
                    parts.append(f"\n![image]({img_file})\n")
                continue

            text = b["text"].strip()
            if not text:
                continue

            if text in hf_texts:
                continue

            page_h = b.get("page_height", 0)
            if page_h:
                rel_y = b["y0"] / page_h
                in_margin = rel_y < 0.10 or rel_y > 0.90
                if in_margin:
                    if hf_patterns and any(p.search(text) for p in hf_patterns):
                        continue
                    if re.match(r"^\d{1,4}$", text):
                        continue
                    if len(text) < 80 and re.search(
                            r"(Sec\.|Chap\.|Chapter|Section)\s*\d",
                            text, re.IGNORECASE):
                        continue

            btype = cls._classify_block(b, body_size)

            if btype == "page_number":
                continue

            if btype == "heading":
                parts.append(f"\n## {text}\n")
            elif btype == "code":
                parts.append(f"\n```\n{text}\n```\n")
            elif btype == "caption":
                parts.append(f"\n**{text}**\n")
            else:
                parts.append(text)

        raw = "\n".join(parts)

        # Fix hyphenated word breaks: "proc-\nessing" → "processing"
        raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)

        # Fix dangling punctuation
        raw = re.sub(r"\n([,;:])", r" \1", raw)

        # Join broken lines within paragraphs (not inside code blocks)
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
                       and not line.strip().startswith("##")
                       and not line.strip().startswith("**")
                       and lines[j + 1].strip()
                       and not lines[j + 1].strip().startswith("##")
                       and not lines[j + 1].strip().startswith("**")
                       and (re.match(r"^[a-z,;(]", lines[j + 1].strip())
                            or re.search(r"[,;]\s*$", line.rstrip())
                            or re.search(
                                r"\b(the|a|an|of|in|to|for|and|or|is|are|by|"
                                r"on|with|from|that|which|as|but|not|if|at|"
                                r"be|has|have|this|than|may|can|also|when|"
                                r"each|into|between|all|more|both|they|"
                                r"their|these|it|such)\s*$",
                                line.rstrip(), re.IGNORECASE))):
                    next_line = lines[j + 1].strip()
                    line = line.rstrip() + " " + next_line
                    j += 1
                merged.append(line)
                j += 1
            result_parts.append("\n".join(merged))

        raw = "".join(result_parts)

        # Collapse multiple blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)

        return raw.strip()
