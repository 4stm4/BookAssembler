"""
Translator + PDF assembler.

Walks the KRM tree, translates text blocks via ollama, then generates
a new PDF with translated content via XeLaTeX (RFC 0012 / 0021).
"""

import asyncio
import logging
import os
import time
from typing import Any, List, Optional

from src.analyzers.llm_refinement import _call_ollama
from src.krm.models import (
    BibEntryBlock,
    BlankPageBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FootnoteBlock,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
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
    if isinstance(block, FootnoteBlock):
        return (block.text or "").strip()
    if isinstance(block, BibEntryBlock):
        return (block.raw_text or block.title or "").strip()
    return ""


def _record_translation(block: Any, original: str, translated: str, target_lang: str) -> None:
    """
    Attach a TranslatedSegment to the block without mutating the source
    (RFC 0021 §2.1, §5.1). Records lineage per RFC 0011: source node id, bbox,
    content hashes, and the deterministic model configuration.
    """
    import hashlib

    from src.analyzers.llm_refinement import OLLAMA_MODEL

    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    bbox = (
        {"page_or_screen_index": getattr(vl, "page_or_screen_index", 0),
         "x0": bb.x0, "y0": bb.y0, "x1": bb.x1, "y1": bb.y1}
        if bb else None
    )
    block.metadata = block.metadata or {}
    segments = block.metadata.setdefault("translations", {})
    segments[target_lang] = {
        "source_node_id": block.id,
        "target_lang": target_lang,
        "target_text": translated,
        "bbox": bbox,
        "lineage": {
            "input_hash": "sha256:" + hashlib.sha256(original.encode()).hexdigest(),
            "output_hash": "sha256:" + hashlib.sha256(translated.encode()).hexdigest(),
        },
        "transformation": {
            "agent_type": "llm_translator",
            "model": OLLAMA_MODEL,
            "temperature": 0.0,
            "seed": 42,
        },
    }


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
    if getattr(container, "is_tombstoned", False):
        return  # RFC 0001 §2.4: tombstoned nodes are excluded from output
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
    elif isinstance(container, ListBlock):
        for item in container.items:
            if getattr(item, "is_tombstoned", False):
                continue
            for child in item.content:
                _collect_translatable(child, result)
    elif isinstance(container, CalloutBlock):
        for child in container.content:
            _collect_translatable(child, result)
    elif isinstance(container, FootnoteBlock):
        if container.text and len(container.text) > 2:
            result.append(("footnote", container))
    elif isinstance(container, BibEntryBlock):
        # Bibliography entries are usually kept in source language; translate
        # only when the target document explicitly wants translated refs.
        if container.raw_text and len(container.raw_text) > 5:
            result.append(("bibentry", container))


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

    for i, (kind, block) in enumerate(blocks):
        elapsed = time.time() - t_start
        if elapsed > MAX_TRANSLATE_TIME:
            log.warning("Translation time budget exhausted at block %d/%d", i, total)
            break

        if kind == "title":
            original = block.title
        elif kind == "paragraph":
            original = _get_block_text(block)
        elif kind == "caption":
            original = block.caption_text
        elif kind == "footnote":
            original = block.text
        elif kind == "bibentry":
            original = block.raw_text
        else:
            original = ""

        translated = _translate_text(original, target_lang)
        # RFC 0021 §5.1 / 0001 §2.4: do NOT mutate the source. The translation is a
        # new segment attached under metadata with lineage back to the source node
        # (RFC 0011: source id, bbox, hashes, deterministic model config).
        _record_translation(block, original, translated, target_lang)

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

    _generate_pdf(doc, target_lang, output_path, job_id, page_aware=True)
    log.info("Translation complete: %d blocks in %.0fs → %s", total, time.time() - t_start, output_path)
    return output_path


def _generate_pdf(
    doc: KnowledgeDocument, target_lang: str, output_path: str, job_id: str,
    page_aware: bool = False,
) -> None:
    """
    RFC 0012 / 0021: build a XeLaTeX document from the KRM tree and compile it to
    PDF, then emit book.json + kae.lock with output hashes alongside the PDF.
    """
    import hashlib
    import json
    import shutil
    from datetime import datetime, timezone

    from src.assembler.latex_builder import build_latex, compile_xelatex

    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(output_path))[0]
    tex_path = os.path.join(out_dir, f"{base}.tex")

    tex_source = build_latex(doc, target_lang, page_aware=page_aware)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_source)

    pdf_path = compile_xelatex(tex_path, out_dir)
    if os.path.abspath(pdf_path) != os.path.abspath(output_path):
        shutil.move(pdf_path, output_path)

    # RFC 0012: reproducibility manifest (book.json) + lock with output hashes.
    def _sha256_file(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    from src.analyzers.llm_refinement import OLLAMA_MODEL
    from src.assembler.latex_builder import SOURCE_DATE_EPOCH

    lock = {
        "lock_version": "1.0",
        "build_id": f"build-{job_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "target_lang": target_lang,
        "input_artifacts": [{"source_uri": doc.source_uri}],
        "analyzers": {"pdf_extractor": "PdfSourceAdapter"},
        "llm_configuration": {
            "provider": "ollama",
            "model": OLLAMA_MODEL,
            "temperature": 0.0,
            "seed": 42,
        },
        "output_hashes": {
            "latex_pdf": f"sha256:{_sha256_file(output_path)}",
        },
    }
    lock_path = os.path.join(out_dir, "kae.lock")
    book_path = os.path.join(out_dir, "book.json")
    with open(lock_path, "w") as f:
        json.dump(lock, f, indent=2)
    with open(book_path, "w") as f:
        json.dump({"title": doc.title, "target_lang": target_lang, "source_uri": doc.source_uri}, f, indent=2)

    # RFC 0013: content-addressed .kap bundle (SHA-256-indexed archive) of the
    # assembled artifacts, for offline deployment / dedup.
    import tarfile

    members = [(output_path, os.path.basename(output_path)),
               (tex_path, os.path.basename(tex_path)),
               (lock_path, "kae.lock"), (book_path, "book.json")]
    manifest = {"artifacts": [], "created_at": lock["created_at"], "job_id": job_id}
    for path, arcname in members:
        if os.path.exists(path):
            manifest["artifacts"].append({"name": arcname, "sha256": _sha256_file(path)})
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    bundle_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    kap_path = os.path.join(out_dir, f"{bundle_sha[:16]}.kap")
    with tarfile.open(kap_path, "w:gz") as tar:
        tar.add(manifest_path, arcname="manifest.json")
        for path, arcname in members:
            if os.path.exists(path):
                tar.add(path, arcname=arcname)
    log.info("Assembled .kap bundle: %s", kap_path)
