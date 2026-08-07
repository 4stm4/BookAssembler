import hashlib
import json
import logging
import os

import fitz

from .blocks import extract_page_blocks
from .columns import detect_columns, sort_blocks_by_columns
from .headings import detect_body_font_size, build_heading_hierarchy
from .headers_footers import detect_headers_footers
from .images import save_page_images
from .lang import get_continuation_pattern
from .ocr import ocr_page
from .text import build_page_text

log = logging.getLogger("bookassembler")


class BookExtractor:
    def __init__(self, pdf_path: str, cache_dir: str = "cache/text",
                 images_dir: str = "cache/images", source_lang: str = "en"):
        self.pdf_path = pdf_path
        self.cache_dir = cache_dir
        self.images_dir = images_dir
        self.source_lang = source_lang
        self._continuation_re = get_continuation_pattern(source_lang)

    def extract(self, start: int, end: int) -> str:
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

        toc = doc.get_toc(simple=True)
        toc_map: dict[int, list[tuple[int, str]]] = {}
        for level, title, page_num in toc:
            pg = page_num - 1
            toc_map.setdefault(pg, []).append((level, title))
        if toc:
            log.info("TOC: %d записей из PDF bookmarks", len(toc))

        page_blocks: dict[str, list[dict]] = {}
        all_blocks: list[dict] = []
        img_dir = os.path.join(self.images_dir, f"pages_{start}_{end}")
        os.makedirs(img_dir, exist_ok=True)
        img_count = 0

        for i in range(start, end + 1):
            if i >= len(doc):
                break
            page = doc[i]
            blocks = extract_page_blocks(page)

            text_blocks = [b for b in blocks if b["block_type"] == "text"]
            if not text_blocks:
                ocr_text = ocr_page(page)
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

            img_count += save_page_images(doc, page, i, blocks, img_dir)

            if i in toc_map:
                for b in blocks:
                    b["_toc_entries"] = toc_map[i]

            page_blocks[str(i)] = blocks
            all_blocks.extend(blocks)

        doc.close()
        if img_count:
            log.info("Сохранено %d изображений -> %s", img_count, img_dir)

        body_size = detect_body_font_size(all_blocks)
        if body_size:
            log.info("Размер основного шрифта: %d pt", body_size)

        heading_levels = build_heading_hierarchy(all_blocks, body_size)
        hf_texts, hf_patterns = detect_headers_footers(all_blocks, len(page_blocks))
        if hf_texts or hf_patterns:
            log.info("Колонтитулы: %d точных, %d паттернов", len(hf_texts), len(hf_patterns))

        texts = {}
        for pg, blocks in page_blocks.items():
            texts[pg] = build_page_text(
                blocks, body_size, heading_levels, hf_texts, hf_patterns,
            )

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(texts, f, ensure_ascii=False, indent=2)

        with open(hash_file, "w") as f:
            f.write(self._pdf_hash())

        log.info("Извлечено %d страниц -> %s", len(texts), cache_file)
        return cache_file

    def _pdf_hash(self, chunk_size: int = 65536) -> str:
        h = hashlib.md5()
        with open(self.pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
