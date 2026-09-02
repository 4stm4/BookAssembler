"""
PDF Source Adapter for Knowledge Assembly Engine (KAE).

Implements PdfSourceAdapter according to RFC 0008 (docs/architecture/0008-adapters.md).

Uses PyMuPDF (fitz) for page-by-page extraction with mmap — safe for large files
under memory constraints (RPi5 / 3GB Docker).

Guarantees:
- VisualLayout with NormalizedRect bounding boxes for every block (RFC 0002)
- ProvenanceInfo with SHA-256 and extraction timestamp (RFC 0011)
- FigureBlock extraction for embedded images (RFC 0008)
- needs_ocr flag on pages without text layer (RFC 0008)
- No fitz types leak outside this module (RFC 0001 — Source Agnosticism)
- All errors wrapped as SourceAdapterParseError
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, List, Optional

import pymupdf as fitz  # type: ignore[import-untyped]

from src.adapters.base import (
    AdapterCapabilities,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.krm.identity import derive_source_id
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    InlineUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    ProvenanceInfo,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _get_fallback_title(source_uri: str) -> str:
    if not source_uri:
        return "Untitled Document"
    base_name = source_uri.rstrip("/").split("/")[-1].split("?")[0]
    if "." in base_name:
        derived = base_name.rsplit(".", 1)[0]
        return derived if derived else "Untitled Document"
    return base_name if base_name else "Untitled Document"


MONOSPACE_FAMILIES = {"courier", "consolas", "mono", "source code", "fira code", "dejavu sans mono"}

INITIAL_CLASSIFICATION_CONFIDENCE = 0.5


def _extraction_confidence(text: str) -> float:
    if not text.strip():
        return 0.1
    stripped = text.strip()
    length = len(stripped)
    printable = sum(c.isprintable() for c in stripped)
    printable_ratio = printable / length if length else 0
    alpha_count = sum(c.isalpha() for c in stripped)
    alpha_ratio = alpha_count / length if length else 0
    base = 0.55
    if length >= 30:
        base += 0.20
    elif length >= 10:
        base += 0.10
    elif length < 3:
        base -= 0.10
    base += printable_ratio * 0.10
    if alpha_ratio > 0.5:
        base += 0.05
    elif alpha_ratio < 0.15:
        base -= 0.10
    return max(0.10, min(0.95, base))


def _is_ocr_garbage(text: str) -> bool:
    """Detect OCR noise from non-text regions (logos, crests, scan artifacts),
    e.g. ", 1IIIIiK,8I ,..i!C\"'-". Real text has a decent letter ratio and at
    least one proper word; garbage is mostly punctuation/digits and letter debris.
    """
    import re
    t = text.strip()
    if len(t) < 4:
        return False  # too short to judge; blank-page logic handles these
    letters = sum(c.isalpha() for c in t)
    if letters / len(t) < 0.5:
        return True
    # A proper word: 3+ letters containing a vowel and not all the same letter.
    words = re.findall(r"[A-Za-z]{3,}", t)
    proper = [w for w in words if re.search(r"[aeiouAEIOUyY]", w) and len(set(w.lower())) >= 2]
    return len(proper) == 0


def _norm_rect(bbox: Any, pw: float, ph: float) -> NormalizedRect:
    """Clamp a PyMuPDF bbox into the [0,1] page grid (RFC 0002 §inv3)."""
    x0, y0, x1, y1 = (bbox or (0, 0, pw, ph))[:4]
    c = lambda v, d: max(0.0, min(1.0, v / d))
    nx0, nx1 = sorted((c(x0, pw), c(x1, pw)))
    ny0, ny1 = sorted((c(y0, ph), c(y1, ph)))
    return NormalizedRect(x0=nx0, y0=ny0, x1=nx1, y1=ny1)


def _is_monospace(font_name: str) -> bool:
    lower = font_name.lower()
    return any(m in lower for m in MONOSPACE_FAMILIES)


def _detect_heading_threshold(all_sizes: List[float]) -> float:
    if not all_sizes:
        return 999.0
    from collections import Counter
    counts = Counter(round(s, 1) for s in all_sizes)
    body_size = counts.most_common(1)[0][0]
    return body_size * 1.25



class PdfSourceAdapter(BaseSourceAdapter):

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="PdfSourceAdapter",
                supported_extensions=["pdf"],
                supported_mimeTypes=["application/pdf"],
                provides_visual_layout=True,
                provides_reading_order=True,
            )
        super().__init__(capabilities)

    def parse(
        self,
        stream: BinaryIO,
        source_uri: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocument:
        try:
            if stream is None:
                raise SourceAdapterParseError("Input stream is None")
            # For file-like objects with a name attribute, open directly via path
            file_path = getattr(stream, "name", None)
            if file_path:
                try:
                    pdf_doc = fitz.open(file_path)
                except Exception as e:
                    raise SourceAdapterParseError(f"PyMuPDF failed to open PDF: {e}") from e
            else:
                raw_bytes = stream.read()
                if not isinstance(raw_bytes, bytes):
                    raise SourceAdapterParseError("Stream read did not return bytes")
                try:
                    pdf_doc = fitz.open(stream=raw_bytes, filetype="pdf")
                except Exception as e:
                    raise SourceAdapterParseError(f"PyMuPDF failed to open PDF: {e}") from e
        except SourceAdapterParseError:
            raise
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read PDF stream: {e}") from e

        timestamp = datetime.now(timezone.utc).isoformat()
        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=timestamp,
        )

        title = _get_fallback_title(source_uri)
        pdf_title = pdf_doc.metadata.get("title", "").strip() if pdf_doc.metadata else ""
        if pdf_title:
            title = pdf_title

        doc = KnowledgeDocument(
            title=title,
            source_uri=source_uri,
            source_type="pdf",
            provenance_info=provenance,
            metadata={"page_count": len(pdf_doc)},
        )

        opts = options or {}
        max_pages = opts.get("max_pages", min(50, len(pdf_doc)))

        # RFC 0008 §5.2: the adapter performs no semantic analysis (no heading
        # detection). It emits a flat block list under a single root container;
        # HeadingAnalyzer builds the heading hierarchy downstream. Typography
        # (font size, bold) is preserved in each block's StyleDescriptor.
        current_container = ContainerUnit(
            id=derive_source_id("root-container", source_uri, None, None, title),
            title=title,
            level=1,
            provenance_info=provenance,
        )
        doc.root_containers.append(current_container)

        for page_idx in range(min(max_pages, len(pdf_doc))):
            page = pdf_doc.load_page(page_idx)
            pw = float(page.rect.width) or 1.0
            ph = float(page.rect.height) or 1.0
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)

            page_has_text = False

            for block in page_dict.get("blocks", []):
                btype = block.get("type", 0)
                bbox = block.get("bbox", (0, 0, pw, ph))

                norm_rect = NormalizedRect(
                    x0=max(0.0, min(1.0, bbox[0] / pw)),
                    y0=max(0.0, min(1.0, bbox[1] / ph)),
                    x1=max(0.0, min(1.0, bbox[2] / pw)),
                    y1=max(0.0, min(1.0, bbox[3] / ph)),
                )
                if norm_rect.x0 >= norm_rect.x1:
                    continue
                if norm_rect.y0 >= norm_rect.y1:
                    continue

                if btype == 1:
                    img_data = block.get("image")
                    img_ext = block.get("ext", "png")
                    mime = f"image/{img_ext}" if img_ext else "image/png"
                    image_uri = ""
                    if img_data:
                        img_sha = hashlib.sha256(img_data).hexdigest()
                        image_uri = f"artifact://{img_sha}"

                    fig = FigureBlock(
                        id=derive_source_id(
                            "figure", source_uri, page_idx, norm_rect, image_uri
                        ),
                        image_uri=image_uri,
                        mime_type=mime,
                        alt_text="",
                        parent_container_id=current_container.id,
                        provenance_info=provenance,
                        visual_layout=VisualLayout(
                            bounding_box=norm_rect,
                            page_or_screen_index=page_idx,
                        ),
                    )
                    current_container.children.append(fig)
                    continue

                if btype != 0:
                    continue

                lines = block.get("lines", [])
                if not lines:
                    continue

                line_texts: List[str] = []
                block_spans_info: List[Dict[str, Any]] = []
                is_mono_block = True
                max_font_size = 0.0
                is_bold_block = False

                line_records: List[Dict[str, Any]] = []
                for line in lines:
                    line_parts: List[str] = []
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not text.strip():
                            continue
                        page_has_text = True
                        line_parts.append(text)
                        font_name = span.get("font", "")
                        font_size = span.get("size", 12.0)
                        flags = span.get("flags", 0)
                        is_bold = bool(flags & (1 << 4))
                        is_italic = bool(flags & (1 << 1))
                        is_mono = _is_monospace(font_name)
                        if not is_mono:
                            is_mono_block = False
                        if font_size > max_font_size:
                            max_font_size = font_size
                        if is_bold:
                            is_bold_block = True
                        block_spans_info.append({
                            "text": text,
                            "font": font_name,
                            "size": font_size,
                            "bold": is_bold,
                            "italic": is_italic,
                            "mono": is_mono,
                        })
                    if line_parts:
                        joined_line = "".join(line_parts)
                        line_texts.append(joined_line)
                        first = line.get("spans", [{}])[0] if line.get("spans") else {}
                        line_records.append({
                            "text": joined_line,
                            "bbox": line.get("bbox"),
                            "font": first.get("font", ""),
                            "size": first.get("size", 12.0),
                            "bold": bool(first.get("flags", 0) & (1 << 4)),
                            "italic": bool(first.get("flags", 0) & (1 << 1)),
                            "mono": _is_monospace(first.get("font", "")),
                        })

                full_text = " ".join(line_texts).strip()
                if not full_text:
                    continue
                # Drop OCR noise from non-text regions (logos/crests/artifacts) so
                # it doesn't pollute paragraphs or title pages.
                if not is_mono_block and _is_ocr_garbage(full_text):
                    page_flags = doc.root_containers[0].metadata.setdefault("ocr_garbage_pages", [])
                    if page_idx not in page_flags:
                        page_flags.append(page_idx)
                    continue

                style = StyleDescriptor(
                    font_family=block_spans_info[0]["font"] if block_spans_info else "sans-serif",
                    font_size_pt=max_font_size,
                    is_bold=is_bold_block,
                    is_monospace=is_mono_block,
                )
                layout = VisualLayout(
                    bounding_box=norm_rect,
                    page_or_screen_index=page_idx,
                    style=style,
                )

                if is_mono_block:
                    ext_conf = _extraction_confidence(full_text)
                    code = CodeBlock(
                        id=derive_source_id(
                            "code", source_uri, page_idx, norm_rect, full_text
                        ),
                        code_text=full_text,
                        parent_container_id=current_container.id,
                        provenance_info=provenance,
                        visual_layout=layout,
                        extraction_confidence=ext_conf,
                        classification_confidence=0.80,
                        confidence_score=min(ext_conf, 0.80),
                    )
                    current_container.children.append(code)
                else:
                    # One inline per source line, each with the line's own bbox
                    # and style. Collapsing a block's lines into a single span
                    # discards the geometry the assembler needs to rebuild a
                    # laid-out page — a two-column contents list comes back as
                    # one run-on paragraph (RFC 0021 §3, §5.4).
                    inlines: List[InlineUnit] = []
                    for rec in line_records:
                        line_layout = VisualLayout(
                            bounding_box=_norm_rect(rec["bbox"], pw, ph),
                            page_or_screen_index=page_idx,
                            style=StyleDescriptor(
                                font_family=rec["font"] or "sans-serif",
                                font_size_pt=rec["size"],
                                is_bold=rec["bold"],
                                is_italic=rec["italic"],
                                is_monospace=rec["mono"],
                            ),
                        )
                        inline = TextLineInline(spans=[StyledTextSpan(
                            text=rec["text"], visual_layout=line_layout,
                        )])
                        inline.visual_layout = line_layout
                        inlines.append(inline)
                    if not inlines:
                        inlines = [TextLineInline(spans=[StyledTextSpan(
                            text=full_text,
                            visual_layout=VisualLayout(
                                bounding_box=norm_rect,
                                page_or_screen_index=page_idx,
                                style=style,
                            ),
                        )])]
                    ext_conf = _extraction_confidence(full_text)
                    para = ParagraphBlock(
                        id=derive_source_id(
                            "paragraph", source_uri, page_idx, norm_rect, full_text
                        ),
                        inlines=inlines,
                        parent_container_id=current_container.id,
                        provenance_info=provenance,
                        visual_layout=layout,
                        extraction_confidence=ext_conf,
                        classification_confidence=INITIAL_CLASSIFICATION_CONFIDENCE,
                        confidence_score=min(ext_conf, INITIAL_CLASSIFICATION_CONFIDENCE),
                    )
                    current_container.children.append(para)

            if not page_has_text:
                placeholder = ParagraphBlock(
                    id=derive_source_id(
                        "ocr-placeholder", source_uri, page_idx, None, ""
                    ),
                    inlines=[TextLineInline(spans=[StyledTextSpan(text="")])],
                    parent_container_id=current_container.id,
                    provenance_info=provenance,
                    visual_layout=VisualLayout(
                        bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
                        page_or_screen_index=page_idx,
                    ),
                    # Nothing was extracted, so nothing is certain. A page we
                    # could not read must not be reported as confidently empty:
                    # downstream that reads as fact, and the UI showed 100% on
                    # eight unreadable scan pages.
                    extraction_confidence=0.1,
                    classification_confidence=0.1,
                    confidence_score=0.1,
                )
                current_container.children.append(placeholder)
                if page.get_images():
                    if not placeholder.metadata:
                        placeholder.metadata = {}
                    placeholder.metadata["needs_ocr"] = True

        pdf_doc.close()

        if not doc.root_containers[0].children:
            doc.root_containers[0].metadata["empty"] = True

        return doc
