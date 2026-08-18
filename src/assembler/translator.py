"""
Translator + PDF assembler.

Walks the KRM tree, translates text blocks via ollama, then generates
a new PDF with translated content using reportlab.
"""

import asyncio
import logging
import os
import time
from typing import Any, List, Optional

from src.analyzers.llm_refinement import _call_ollama
from src.krm.models import (
    BlankPageBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TableBlock,
    TitlePageBlock,
)

log = logging.getLogger(__name__)

MAX_TRANSLATE_TIME = 3600


def _get_block_text(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        parts = []
        for inline in (block.inlines or []):
            for span in getattr(inline, "spans", []):
                if hasattr(span, "text"):
                    parts.append(span.text)
        return " ".join(parts).strip()
    if isinstance(block, ContainerUnit):
        return (block.title or "").strip()
    if isinstance(block, CaptionBlock):
        return (block.caption_text or "").strip()
    if isinstance(block, CodeBlock):
        return (block.code_text or "").strip()
    return ""


def _translate_text(text: str, target_lang: str) -> str:
    if not text.strip() or len(text.strip()) < 3:
        return text
    prompt = (
        f"Translate to {target_lang}. Output ONLY the translation.\n\n"
        f"{text}"
    )
    result = _call_ollama(prompt)
    return result.strip() if result else text


def _collect_translatable(container: Any, result: list) -> None:
    if isinstance(container, ContainerUnit):
        if container.title and len(container.title.strip()) > 2:
            result.append(("title", container))
        for child in container.children:
            _collect_translatable(child, result)
    elif isinstance(container, ParagraphBlock) and not isinstance(container, (BlankPageBlock,)):
        text = _get_block_text(container)
        if text and len(text) > 2:
            result.append(("paragraph", container))
    elif isinstance(container, CaptionBlock):
        if container.caption_text and len(container.caption_text) > 2:
            result.append(("caption", container))


def translate_and_assemble(
    doc: KnowledgeDocument,
    target_lang: str,
    output_path: str,
    job_id: str,
    pyjobkit_bridge: Any = None,
    loop: Any = None,
) -> str:
    blocks: list = []
    for container in doc.root_containers:
        _collect_translatable(container, blocks)

    total = len(blocks)
    log.info("Translating %d blocks to %s", total, target_lang)
    t_start = time.time()

    translated_pages: dict = {}

    for i, (kind, block) in enumerate(blocks):
        elapsed = time.time() - t_start
        if elapsed > MAX_TRANSLATE_TIME:
            log.warning("Translation time budget exhausted at block %d/%d", i, total)
            break

        if kind == "title":
            original = block.title
            translated = _translate_text(original, target_lang)
            block.metadata = block.metadata or {}
            block.metadata["original_title"] = original
            block.title = translated
        elif kind == "paragraph":
            original = _get_block_text(block)
            translated = _translate_text(original, target_lang)
            from src.krm.models import TextLineInline, StyledTextSpan
            block.inlines = [TextLineInline(spans=[StyledTextSpan(text=translated)])]
            block.metadata = block.metadata or {}
            block.metadata["original_text"] = original
        elif kind == "caption":
            original = block.caption_text
            translated = _translate_text(original, target_lang)
            block.metadata = block.metadata or {}
            block.metadata["original_caption"] = original
            block.caption_text = translated

        vl = getattr(block, "visual_layout", None)
        pg = vl.page_or_screen_index if vl else 0
        text = _get_block_text(block) if kind != "title" else block.title
        translated_pages.setdefault(pg, []).append(text)

        if pyjobkit_bridge and loop and i % 5 == 0:
            try:
                asyncio.run_coroutine_threadsafe(
                    pyjobkit_bridge.publish_event({
                        "type": "job_progress",
                        "job_id": job_id,
                        "stage": f"Перевод: {i+1}/{total}",
                        "progress": (i + 1) / total,
                    }),
                    loop,
                )
            except Exception:
                pass

        if (i + 1) % 10 == 0:
            log.info("Translated %d/%d blocks (%.0fs)", i + 1, total, time.time() - t_start)

    _generate_pdf(doc, translated_pages, output_path)
    log.info("Translation complete: %d blocks in %.0fs → %s", total, time.time() - t_start, output_path)
    return output_path


def _generate_pdf(doc: KnowledgeDocument, pages: dict, output_path: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        log.warning("reportlab not installed, writing plain text instead")
        with open(output_path.replace(".pdf", ".txt"), "w") as f:
            for pg in sorted(pages.keys()):
                f.write(f"\n--- Page {pg + 1} ---\n")
                for text in pages[pg]:
                    f.write(text + "\n")
        return

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("DejaVu", font_path))
        base_font = "DejaVu"
    else:
        base_font = "Helvetica"

    pdf_doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle(
        "TransNormal", parent=styles["Normal"],
        fontName=base_font, fontSize=11, leading=14,
    )
    style_heading = ParagraphStyle(
        "TransHeading", parent=styles["Heading1"],
        fontName=base_font, fontSize=16, leading=20, spaceAfter=12,
    )
    style_title = ParagraphStyle(
        "TransTitle", parent=styles["Title"],
        fontName=base_font, fontSize=22, leading=26, spaceAfter=20,
    )

    story: list = []

    def _add_container(container: Any, depth: int = 0) -> None:
        if isinstance(container, ContainerUnit):
            if container.title:
                s = style_title if depth == 0 else style_heading
                safe = container.title.replace("&", "&amp;").replace("<", "&lt;")
                story.append(Paragraph(safe, s))
                story.append(Spacer(1, 6))
            for child in container.children:
                _add_container(child, depth + 1)
        elif isinstance(container, BlankPageBlock):
            story.append(PageBreak())
        elif isinstance(container, TitlePageBlock):
            title = getattr(container, "book_title", "") or ""
            if title:
                safe = title.replace("&", "&amp;").replace("<", "&lt;")
                story.append(Paragraph(safe, style_title))
            text = _get_block_text(container)
            if text:
                safe = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
                story.append(Paragraph(safe, style_normal))
            story.append(PageBreak())
        elif isinstance(container, ParagraphBlock):
            text = _get_block_text(container)
            if text:
                safe = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
                story.append(Paragraph(safe, style_normal))
                story.append(Spacer(1, 4))
        elif isinstance(container, CaptionBlock):
            text = container.caption_text or ""
            if text:
                safe = text.replace("&", "&amp;").replace("<", "&lt;")
                story.append(Paragraph(f"<i>{safe}</i>", style_normal))
        elif isinstance(container, CodeBlock):
            text = container.code_text or ""
            if text:
                safe = text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
                story.append(Paragraph(f"<font face='Courier' size='9'>{safe}</font>", style_normal))
                story.append(Spacer(1, 4))

    for root in doc.root_containers:
        _add_container(root)

    if story:
        pdf_doc.build(story)
    else:
        log.warning("No content to build PDF")
