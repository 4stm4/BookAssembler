"""
Translation of a KRM document and assembly of the translated book (RFC 0021).

Translation runs over *units*: a heading, a paragraph, a caption, a footnote,
a contents entry — or a sentence the page break cut in two, sent as one piece
so it comes back as one sentence rather than two halves translated blind.
Every finished unit is recorded at once as a TranslatedSegment in the
metadata of its blocks (the source is never mutated, §5.1), so a job that
stops — a crash, a deploy, a GPU session that ran out — resumes where it
stopped: a unit whose segment was made from the same source text with the
same prompt is not sent again (§2.2).

The work is shared by every reachable agent that declares the `translate`
role: the GPU runner (RFC 0022) with a couple of requests in flight, and each
edge-cluster ollama as a worker of its own — ollama answers one request at a
time. A unit an agent failed goes back to the queue for any worker. A reply
that is not a translation (empty, the source echoed back, another script) is
never recorded as one: the renderer then keeps the source, which shows,
instead of passing English off as Russian.

Assembly (`assemble_book`) only renders; it never calls a model.
"""

import hashlib
import logging
import os
import queue
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from src.agents.text import generate_text
from src.krm.models import (
    BibEntryBlock,
    CalloutBlock,
    CaptionBlock,
    ContainerUnit,
    FootnoteBlock,
    KnowledgeDocument,
    ListBlock,
    MathInline,
    ParagraphBlock,
    TitlePageBlock,
    TocEntryBlock,
)

log = logging.getLogger(__name__)

# RFC 0015 §4: WER above this escalates the segment to human review.
DRIFT_WER_THRESHOLD = 0.15

# One paragraph of "Programming the Z80" is ~230 tokens of Russian; a 7B model
# on the rpi5 CPU makes 1.9 tokens/s. Minutes per unit are normal there.
EDGE_TIMEOUT = int(os.environ.get("KAE_TRANSLATE_EDGE_TIMEOUT", "900"))
GPU_TIMEOUT = int(os.environ.get("KAE_TRANSLATE_GPU_TIMEOUT", "300"))
# Requests kept in flight on a GPU agent; its Manager queues the rest (RFC 0022 §5.6).
GPU_WORKERS = int(os.environ.get("KAE_TRANSLATE_GPU_WORKERS", "2"))
MAX_ATTEMPTS = 3
# An agent that failed this many units in a row is down, not unlucky.
RETIRE_AFTER = 5


def _build_translate_prompt(text: str, target_lang: str) -> str:
    return (
        f"You are translating a technical book on computers and programming into {target_lang}.\n"
        "Rules:\n"
        "- Keep instruction mnemonics, register and signal names, numbers, hexadecimal "
        "and binary values, labels and program code exactly as written.\n"
        f"- Use the established {target_lang} terminology of the field.\n"
        "- Translate everything and add nothing. Output only the translation: "
        "no notes, quotes or explanations.\n\n"
        f"Text:\n{text}"
    )


# ── source text ─────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def join_lines(lines: Iterable[str]) -> str:
    """Printed lines as one text: a word hyphenated at the end of a line is
    whole again ("in-" + "cremented"), everything else joins with a space."""
    out = ""
    for raw in lines:
        line = _WS.sub(" ", raw or "").strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and line[0].islower():
            out = out[:-1] + line
        else:
            out = f"{out} {line}"
    return out


def _line_text(inline: Any) -> str:
    if isinstance(inline, MathInline):
        return f"${inline.latex_code}$" if inline.latex_code else ""
    out = ""
    for span in getattr(inline, "spans", None) or []:
        text = getattr(span, "text", "") or ""
        # Spans split a line where the style changes and carry their own
        # spaces; only two spans that would glue two words together need one.
        if out and text and out[-1].isalnum() and text[0].isalnum():
            out += " "
        out += text
    return out


def source_text(kind: str, node: Any) -> str:
    if kind == "title":
        return join_lines([node.title or ""])
    if kind == "toc":
        return join_lines([node.entry_text or ""])
    if kind == "caption":
        return join_lines([node.caption_text or ""])
    if kind == "footnote":
        return join_lines([node.text or ""])
    if kind == "bibentry":
        return join_lines([node.raw_text or node.title or ""])
    return join_lines(_line_text(i) for i in (node.inlines or []))


def _walk(node: Any) -> Iterator[Tuple[str, Any]]:
    """Translatable nodes in reading order. Code, formulas, tables and figures
    are atomic and go through as they are (RFC 0021 §2.3)."""
    if getattr(node, "is_tombstoned", False):
        return  # RFC 0001 §2.4: tombstoned nodes are excluded from output
    if isinstance(node, ContainerUnit):
        if node.title:
            yield "title", node
        for child in node.children:
            yield from _walk(child)
    elif isinstance(node, ParagraphBlock):
        yield "paragraph", node
    elif isinstance(node, TocEntryBlock):
        yield "toc", node
    elif isinstance(node, CaptionBlock):
        yield "caption", node
    elif isinstance(node, FootnoteBlock):
        yield "footnote", node
    elif isinstance(node, BibEntryBlock):
        yield "bibentry", node
    elif isinstance(node, ListBlock):
        for item in node.items:
            if not getattr(item, "is_tombstoned", False):
                for child in item.content:
                    yield from _walk(child)
    elif isinstance(node, CalloutBlock):
        for child in node.content:
            yield from _walk(child)


# ── units ───────────────────────────────────────────────────────────────────

@dataclass
class Unit:
    """What goes to the model in one request. `blocks[0]` carries the
    translation; any further block is text the page break cut off it."""
    kind: str
    blocks: List[Any]
    texts: List[str]
    text: str
    attempts: int = 0

    @property
    def head(self) -> Any:
        return self.blocks[0]


def _page(node: Any) -> Optional[int]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None


_ENDS_SENTENCE = re.compile(r"[.!?:;)\]\"'»”…]$")


def _continues(prev: Unit, nxt: Unit) -> bool:
    """The page break cut a sentence: the paragraph before it does not end
    one, and the first paragraph after it goes on in lower case."""
    if prev.kind != "paragraph" or nxt.kind != "paragraph":
        return False
    a, b = prev.blocks[-1], nxt.head
    if isinstance(a, TitlePageBlock) or isinstance(b, TitlePageBlock):
        return False
    pa, pb = _page(a), _page(b)
    if pa is None or pb != pa + 1:
        return False
    return not _ENDS_SENTENCE.search(prev.text) and nxt.text[:1].islower()


# Nothing to translate without a word: a hex dump ("0100 3E 10") or a lone
# instruction ("LD A,(HL)") goes through as it is.
_WORDLIKE = re.compile(r"[^\W\d_]{3,}")


def collect_units(doc: KnowledgeDocument) -> List[Unit]:
    units: List[Unit] = []
    for container in doc.root_containers:
        for kind, node in _walk(container):
            text = source_text(kind, node)
            if not _WORDLIKE.search(text):
                continue
            unit = Unit(kind, [node], [text], text)
            if units and _continues(units[-1], unit):
                prev = units[-1]
                prev.blocks.append(node)
                prev.texts.append(text)
                prev.text = join_lines([prev.text, text])
                continue
            units.append(unit)
    return units


# ── segments ────────────────────────────────────────────────────────────────

def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _segment(block: Any, target_lang: str) -> Dict[str, Any]:
    md = getattr(block, "metadata", None) or {}
    return (md.get("translations") or {}).get(target_lang) or {}


def _bbox(block: Any) -> Optional[Dict[str, Any]]:
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if not bb:
        return None
    return {"page_or_screen_index": getattr(vl, "page_or_screen_index", 0),
            "x0": bb.x0, "y0": bb.y0, "x1": bb.x1, "y1": bb.y1}


def _record_translation(
    block: Any, original: str, translated: str, target_lang: str, *,
    prompt: Optional[str] = None, model: Optional[str] = None,
    agent: Optional[str] = None, merged_with: Optional[List[str]] = None,
) -> None:
    """
    Attach a TranslatedSegment to the block without mutating the source
    (RFC 0021 §2.1, §5.1). Records lineage per RFC 0011: source node id, bbox,
    content hashes, and the model configuration that actually answered.
    """
    from src.analyzers.llm_refinement import OLLAMA_MODEL
    from src.benchmark.metrics import compute_technical_drift

    drift = compute_technical_drift(original, translated)
    seg: Dict[str, Any] = {
        "source_node_id": block.id,
        "target_lang": target_lang,
        "source_text": original,
        "target_text": translated,
        "bbox": _bbox(block),
        "lineage": {"input_hash": _sha(original), "output_hash": _sha(translated)},
        "transformation": {
            "agent_type": "llm_translator",
            "agent": agent,
            "model": model or OLLAMA_MODEL,
            "temperature": 0.0,
            "seed": 42,
            "prompt_hash": _sha(prompt if prompt is not None
                                else _build_translate_prompt(original, target_lang)),
        },
        # RFC 0015 §4: drift above the threshold escalates the segment to a
        # human; HITLManager.flag_desynchronized_nodes turns this into a task.
        "drift": {"protected_token_wer": drift, "escalated": drift > DRIFT_WER_THRESHOLD},
    }
    if merged_with:
        seg["merged_with"] = merged_with
    block.metadata = block.metadata or {}
    block.metadata.setdefault("translations", {})[target_lang] = seg


def _record_merged(block: Any, head: Any, original: str, target_lang: str, prompt: str) -> None:
    """A block whose text went out, and came back, inside its head's unit: it
    points there and renders nothing of its own (latex_builder._translated)."""
    block.metadata = block.metadata or {}
    block.metadata.setdefault("translations", {})[target_lang] = {
        "source_node_id": block.id,
        "target_lang": target_lang,
        "source_text": original,
        "target_text": "",
        "merged_into": head.id,
        "bbox": _bbox(block),
        "lineage": {"input_hash": _sha(original)},
        "transformation": {"agent_type": "llm_translator", "prompt_hash": _sha(prompt)},
    }


def is_translated(unit: Unit, target_lang: str) -> bool:
    """Done already: made from this very text with this very prompt."""
    seg = _segment(unit.head, target_lang)
    if not seg.get("target_text"):
        return False
    if (seg.get("lineage") or {}).get("input_hash") != _sha(unit.text):
        return False
    prompt = _build_translate_prompt(unit.text, target_lang)
    if (seg.get("transformation") or {}).get("prompt_hash") != _sha(prompt):
        return False
    return all(_segment(b, target_lang).get("merged_into") == unit.head.id
               for b in unit.blocks[1:])


def _record_unit(unit: Unit, translated: str, target_lang: str, prompt: str, target: "Target") -> None:
    _record_translation(unit.head, unit.text, translated, target_lang, prompt=prompt,
                        model=target.model, agent=target.name,
                        merged_with=[b.id for b in unit.blocks[1:]] or None)
    for block, text in zip(unit.blocks[1:], unit.texts[1:]):
        _record_merged(block, unit.head, text, target_lang, prompt)


# ── is it a translation? ────────────────────────────────────────────────────

_CYRILLIC_TARGETS = {"russian", "ru", "русский", "ukrainian", "uk", "belarusian", "be",
                     "bulgarian", "bg", "serbian", "sr"}
_CYRILLIC = re.compile(r"[а-яёіїєґўА-ЯЁІЇЄҐЎ]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
# Prose words: mnemonics and register names are shorter than five letters.
_PROSE_WORD = re.compile(r"[^\W\d_]{5,}")
_QUOTES = (('"', '"'), ("«", "»"), ("“", "”"))


def _cleaned(reply: str, original: str) -> str:
    text = (reply or "").strip()
    text = re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
    text = re.sub(r"^(?:translation|перевод)\s*:\s*", "", text, flags=re.I).strip()
    for a, b in _QUOTES:
        if len(text) > 2 and text.startswith(a) and text.endswith(b) \
                and not original.lstrip().startswith(a):
            text = text[1:-1].strip()
    return text


def _rejection(original: str, translated: str, target_lang: str) -> Optional[str]:
    """Why the reply is not a translation of `original`, or None."""
    if not translated:
        return "empty reply"
    if _CJK.search(translated) and not _CJK.search(original):
        return "reply in another script"
    if target_lang.strip().lower() in _CYRILLIC_TARGETS:
        if sum(map(len, _PROSE_WORD.findall(original))) >= 10:
            words = _PROSE_WORD.findall(translated)
            cyr = sum(len(w) for w in words if _CYRILLIC.search(w))
            if cyr < 0.5 * max(1, sum(map(len, words))):
                return "reply is not in the target language"
    if len(original) >= 40 and not 0.4 <= len(translated) / len(original) <= 3.5:
        return "reply length out of proportion"
    return None


# ── agents ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Target:
    name: str
    host: str
    model: Optional[str]
    kind: str = "ollama"

    @property
    def gpu(self) -> bool:
        return self.kind != "ollama"


def translation_targets() -> List[Target]:
    """One worker per reachable edge ollama, GPU_WORKERS per reachable GPU
    agent — among the agents that declare the `translate` role; failing any,
    every reachable ollama, as router.pick does for text roles."""
    from src.agents.router import _probe_health, _probe_ollama, load_agents, probe_managed

    def reachable(a: Dict[str, Any]) -> Tuple[bool, List[str]]:
        kind = a.get("kind", "ollama")
        if kind == "managed":
            ok, health = probe_managed(a["host"])
            # Manager reachable is not Runner ready (RFC 0022 §4.1).
            return ok and health.get("runner") == "up", health.get("tasks") or []
        if kind == "multimodel":
            return _probe_health(a["host"])
        if kind == "ollama":
            return _probe_ollama(a["host"])
        return False, []  # OCR-only agents

    def target(a: Dict[str, Any], models: List[str]) -> Target:
        return Target(a.get("name") or a["host"], a["host"],
                      a.get("active_model") or (models[0] if models else None),
                      a.get("kind", "ollama"))

    agents = load_agents()
    out: List[Target] = []
    for a in agents:
        if "translate" in (a.get("roles") or []):
            ok, models = reachable(a)
            if ok:
                t = target(a, models)
                out.extend([t] * (GPU_WORKERS if t.gpu else 1))
    gpu = [t for t in out if t.gpu]
    if gpu:
        # The edge cluster is the degradation path for bulk work (RFC 0022
        # §7.2), not the GPU's partner: at 0.6-1.9 tokens/s it adds next to
        # nothing, and would put a second model's wording into the book.
        return gpu
    if not out:
        for a in agents:
            if a.get("kind", "ollama") == "ollama":
                ok, models = _probe_ollama(a["host"])
                if ok:
                    out.append(target(a, models))
    return out


def _call_target(target: Target, prompt: str) -> Optional[str]:
    if target.gpu:
        from src.agents.router import call_infer
        from src.agents.tasks import Priority
        # One attempt: a timed-out generation goes on running on the Runner,
        # and a retry would queue a copy behind it. The job puts the unit back
        # in the queue itself.
        return call_infer(target.host, "translate", prompt=prompt, kind=target.kind,
                          model=target.model, timeout=GPU_TIMEOUT, attempts=1,
                          priority=int(Priority.BULK))
    # An explicit host goes straight to that ollama and takes no GPU slot.
    return generate_text(prompt, task="translate", host=target.host,
                         model=target.model, timeout=EDGE_TIMEOUT)


# ── the job ─────────────────────────────────────────────────────────────────

@dataclass
class TranslationStats:
    total: int = 0      # units in the document
    cached: int = 0     # translated before this run
    done: int = 0       # translated by this run
    failed: int = 0     # gave up after MAX_ATTEMPTS
    left: int = 0       # not reached: stopped, or every agent gone

    @property
    def processed(self) -> int:
        return self.cached + self.done + self.failed

    def as_dict(self) -> Dict[str, int]:
        return {"total": self.total, "cached": self.cached, "done": self.done,
                "failed": self.failed, "left": self.left}


def translate_document(
    doc: KnowledgeDocument, target_lang: str, targets: List[Target], *,
    lock: Optional[Any] = None,
    on_progress: Optional[Callable[[TranslationStats], None]] = None,
    stop: Optional[threading.Event] = None,
) -> TranslationStats:
    """Translate every unit not translated yet. Segments are recorded under
    `lock` as they come, so whoever persists the document under the same lock
    saves the job's progress as it goes."""
    units = collect_units(doc)
    todo = [u for u in units if not is_translated(u, target_lang)]
    stats = TranslationStats(total=len(units), cached=len(units) - len(todo))
    if not todo:
        return stats
    if not targets:
        raise RuntimeError("no reachable agent for the translate role")

    lock = lock or threading.Lock()
    stop = stop or threading.Event()
    pending: "queue.Queue[Unit]" = queue.Queue()
    for unit in todo:
        pending.put(unit)
    guard = threading.Lock()
    in_flight = [0]

    def take() -> Tuple[Optional[Unit], bool]:
        """The next unit, or (None, finished?). Taking and counting it in
        flight is one step, so no worker sees an empty queue and no work in
        flight while a unit is on its way back to the queue."""
        with guard:
            try:
                unit = pending.get_nowait()
            except queue.Empty:
                return None, in_flight[0] == 0
            in_flight[0] += 1
            return unit, False

    def work(target: Target) -> None:
        failures = 0
        while not stop.is_set() and failures < RETIRE_AFTER:
            unit, finished = take()
            if finished:
                return
            if unit is None:
                stop.wait(0.5)
                continue
            try:
                prompt = _build_translate_prompt(unit.text, target_lang)
                try:
                    reply = _call_target(target, prompt)
                except Exception:  # one agent's fault must not end the job
                    log.exception("translate: %s raised", target.name)
                    reply = None
                translated = _cleaned(reply or "", unit.text)
                why = _rejection(unit.text, translated, target_lang) if reply else "no reply"
                if why is None:
                    with lock:
                        _record_unit(unit, translated, target_lang, prompt, target)
                    failures = 0
                    with guard:
                        stats.done += 1
                else:
                    failures += 1
                    unit.attempts += 1
                    log.warning("translate: %s, page %s, attempt %d: %s",
                                target.name, _page(unit.head), unit.attempts, why)
                    if unit.attempts < MAX_ATTEMPTS:
                        pending.put(unit)
                    else:
                        with guard:
                            stats.failed += 1
            finally:
                with guard:
                    in_flight[0] -= 1
            if on_progress:
                try:
                    on_progress(stats)
                except Exception:
                    log.exception("translate: progress callback failed")
        if failures >= RETIRE_AFTER:
            log.warning("translate: %s failed %d units in a row, leaving the job",
                        target.name, failures)

    threads = [threading.Thread(target=work, args=(t,), name=f"translate-{t.name}", daemon=True)
               for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stats.left = pending.qsize()
    return stats


# ── assembly ────────────────────────────────────────────────────────────────

def assemble_book(doc: KnowledgeDocument, target_lang: str, output_path: str,
                  job_id: str) -> Dict[str, int]:
    """Render the book with the segments it has; a unit without one keeps its
    source text. Returns how much of the book is translated."""
    units = collect_units(doc)
    done = [u for u in units if is_translated(u, target_lang)]
    models = sorted({(_segment(u.head, target_lang).get("transformation") or {}).get("model") or ""
                     for u in done} - {""})
    _generate_pdf(doc, target_lang, output_path, job_id, page_aware=True, models=models)
    return {"units": len(units), "translated": len(done)}


def _generate_pdf(
    doc: KnowledgeDocument, target_lang: str, output_path: str, job_id: str,
    page_aware: bool = False, models: Optional[List[str]] = None,
) -> None:
    """
    RFC 0012 / 0021: build a XeLaTeX document from the KRM tree and compile it to
    PDF, then emit book.json + kae.lock with output hashes alongside the PDF.
    """
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
    from src.analyzers.llm_refinement import OLLAMA_MODEL
    from src.artifacts.store import sha256_file as _sha256_file, write_kap_bundle
    from src.assembler.latex_builder import SOURCE_DATE_EPOCH, toolchain_fingerprint

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
            # The models the segments were actually made with.
            "model": models[0] if models and len(models) == 1 else OLLAMA_MODEL,
            "models": models or [],
            "temperature": 0.0,
            "seed": 42,
        },
        "output_hashes": {
            "latex_pdf": f"sha256:{_sha256_file(output_path)}",
        },
        # RFC 0012 §3.3: which TeX actually produced this PDF — the image installs
        # TeX Live unpinned, so a later rebuild can differ and must be detectable.
        "toolchain": {"xelatex": toolchain_fingerprint()},
    }
    lock_path = os.path.join(out_dir, "kae.lock")
    book_path = os.path.join(out_dir, "book.json")
    with open(lock_path, "w") as f:
        json.dump(lock, f, indent=2)
    with open(book_path, "w") as f:
        json.dump({"title": doc.title, "target_lang": target_lang, "source_uri": doc.source_uri}, f, indent=2)

    # RFC 0013: content-addressed .kap bundle of the assembled artifacts, for
    # offline deployment / dedup. One writer (src/artifacts/store) — the bundle
    # was hand-rolled here and had no reader; kae.lock and build metadata stay
    # out of the content address so identical inputs dedup.
    kap_path = write_kap_bundle(
        out_dir,
        members=[
            (output_path, os.path.basename(output_path)),
            (tex_path, os.path.basename(tex_path)),
            (lock_path, "kae.lock"),
            (book_path, "book.json"),
        ],
        extra_manifest={"created_at": lock["created_at"], "job_id": job_id},
        content_exclude=("kae.lock",),
    )
    log.info("Assembled .kap bundle: %s", kap_path)
