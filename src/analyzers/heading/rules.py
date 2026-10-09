"""heading: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import block_text, font_size
from collections import Counter
import re
from typing import Any, Dict, List, Optional, Sequence
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, UnknownBlock

from src.analyzers.paragraph.rules import continues
from src.analyzers.heading.signals import (
    COLUMN_LINES,
    COLUMN_WORDS,
    HANGING_INDENT_LINES,
    HEAD_ROW_CELLS,
    LARGER_MIN_WEIGHT,
    LARGER_THAN_BODY,
    MAX_HEADING_GAP_LINES,
    MAX_HEADING_LINES,
    MAX_PRINTED_HEADING_WORDS,
    SAME_HEADING_SIZE,
    SAME_ROW,
    SMALLER_THAN_BODY,
    MIN_WORD_CHAR_RATIO,
    MISREAD_CAPITALS,
    _COMMENT_CLOSE_RE,
    _COMMENT_OPEN_RE,
    _NOTE_PREFIX_RE,
    _TRAILING_JUNK_RE,
    _LEADING_NUMBER_RE,
    _WORD_RE,
)


def _word_char_ratio(text: str) -> float:
    """Share of the text's (non-space) characters that belong to a real word
    - or to the number it leads with (_LEADING_NUMBER_RE).

    A diagram label or code comment mangled by OCR can embed one genuine
    word inside a run of symbol noise; this measures how much of the text
    that word actually accounts for, rather than just whether one exists.
    """
    words = [
        w for w in _WORD_RE.findall(text)
        if re.search(r"[aeiouAEIOUyY]", w) and len(set(w.lower())) >= 2
    ]
    words += _LEADING_NUMBER_RE.findall(text.strip())
    total = len(re.sub(r"\s+", "", text))
    if not total:
        return 0.0
    return sum(len(w) for w in words) / total


def _looks_like_non_heading_noise(text: str) -> bool:
    """Syntactic tells the word-ratio check cannot reach: a mangled code
    comment, an inline "NOTE:" annotation, or a diagram/pinout label
    trailing off into scan noise. See signals.py for what each pattern
    was measured against."""
    return bool(
        _COMMENT_OPEN_RE.match(text)
        or _COMMENT_CLOSE_RE.search(text)
        or _NOTE_PREFIX_RE.match(text)
        or _TRAILING_JUNK_RE.search(text)
    )

def _is_monospace(block: Any) -> bool:
    vl = getattr(block, "visual_layout", None)
    st = getattr(vl, "style", None) if vl else None
    return bool(getattr(st, "is_monospace", False)) if st else False

def _detect_heading_threshold(sizes: List[float]) -> float:
    """Body text is the most common font size; headings are ≥25% larger."""
    if not sizes:
        return 999.0
    counts = Counter(round(s, 1) for s in sizes)
    body_size = counts.most_common(1)[0][0]
    return body_size * 1.25

def _heading_level(font_size: float, threshold: float) -> int:
    ratio = font_size / threshold if threshold else 0.0
    if ratio >= 1.4:
        return 1
    if ratio >= 1.15:
        return 2
    return 3

def _reads_as_title(text: str) -> bool:
    """Whether text has a heading's shape: words, not noise."""
    return (
        3 <= len(text) < 200
        and any(c.isalpha() for c in text)
        and _word_char_ratio(text) >= MIN_WORD_CHAR_RATIO
        and not _looks_like_non_heading_noise(text)
    )


def _is_heading(block: Any, threshold: float) -> bool:
    if not isinstance(block, (ParagraphBlock, UnknownBlock)):
        return False
    if _is_monospace(block):
        return False
    return font_size(block, default=12.0) >= threshold and _reads_as_title(block_text(block))


def _printed(block: Any) -> List[Dict[str, Any]]:
    """A block's lines as printed (PrintedLinesAnalyzer), where read."""
    if not isinstance(block, (ParagraphBlock, UnknownBlock)):
        return []
    return list((block.metadata or {}).get("printed_lines") or [])


def _printed_under(blocks: List[Any], start: int) -> List[Dict[str, Any]]:
    """The printed lines of the paragraph blocks[start] starts: it and the
    blocks after it that continue it (paragraph.rules.continues) - OCR cuts
    a paragraph into pieces, and its first line can stand alone."""
    lines: List[Dict[str, Any]] = []
    k = start
    while k < len(blocks) and isinstance(blocks[k], (ParagraphBlock, UnknownBlock)):
        if k > start and not continues(blocks[k - 1], blocks[k]):
            break
        lines += _printed(blocks[k])
        k += 1
    return lines


def _capitals(text: str) -> bool:
    """Whether a line is set in capitals: four letters or more, none
    lowercase but what OCR misread (MISREAD_CAPITALS)."""
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 4 and sum(ch.islower() for ch in letters) <= MISREAD_CAPITALS * len(letters)


def _printed_size(lines: List[Dict[str, Any]]) -> float:
    sizes = sorted(l.get("size") or 0.0 for l in lines)
    return sizes[len(sizes) // 2] if sizes else 0.0


def body_size(blocks: List[Any]) -> float:
    """The size a scanned document's body is printed at: the middle of its
    paragraphs' long lines' of words (PrintedLinesAnalyzer) - a page's
    equations are none: the Intel 3000 manual's "Cn+7 = Y6X6 + Y6Y5X5 +
    ...", set 11pt by its 7.1pt text, made its 8.9pt headings smaller
    than its body. 0 where none was read."""
    sizes = sorted(l["size"] for b in blocks for l in _printed(b)
                   if l.get("size") and len(l.get("text") or "") >= 40
                   and _word_char_ratio(l["text"]) >= MIN_WORD_CHAR_RATIO)
    return sizes[len(sizes) // 2] if sizes else 0.0


def _stands_apart(lines: List[Dict[str, Any]], text: str, body: float) -> str:
    """How a block's printed lines stand apart from the body text: "larger"
    - set larger than it (LARGER_THAN_BODY), and no lighter
    (LARGER_MIN_WEIGHT) - or in its size "bold", "italic" or "capitals",
    every line so; "" where they do not."""
    size = _printed_size(lines)
    if body and size >= LARGER_THAN_BODY * body:
        light = any(l.get("weight") is not None and l["weight"] < LARGER_MIN_WEIGHT for l in lines)
        return "" if light else "larger"
    if body and size < SMALLER_THAN_BODY * body:
        return ""
    if all(l.get("bold") for l in lines):
        return "bold"
    if all(l.get("italic") for l in lines):
        return "italic"
    if _capitals(text):
        return "capitals"
    return ""


def _is_printed_heading(block: Any, under: List[Dict[str, Any]], body: float = 0.0,
                        others: Sequence[Dict[str, Any]] = ()) -> bool:
    """A scanned page's heading: a block of a line or two
    (MAX_HEADING_LINES) reading as a title, that stands apart from the
    body text by its print (_stands_apart) - larger, or in its size bold,
    italic or capitals: the MCS-40 manual's "COMPUTER OPERATIONS", "TIMING:",
    Zaks' italic "1. Binary" - or hanging out to the left of the paragraph
    under it ("PUSH IX" over its instruction). OCR's sizes say none of it.

    One set in the body's size heads the paragraph under it (under, its
    printed lines): one beginning close under it (MAX_HEADING_GAP_LINES),
    across from it, set as body text - a line that stands apart over
    another that does is a table's or a figure's. One set larger may head
    a heading in its turn ("Z80 HARDWARE ORGANIZATION" over
    "INTRODUCTION"); one ending in a colon introduces whatever follows
    close under it - "TEST LOAD CIRCUIT:" its drawing - and one over a
    table's column heads heads the table ("CAPACITANCE(2) TA = 25°C" over
    "SYMBOL PARAMETER MIN TYP MAX UNIT"). A line ending a
    sentence ("in separate sections.") is none, nor one in a row of a
    table's column heads (_in_head_row; others, the page's other printed
    lines)."""
    lines = _printed(block)
    if not 1 <= len(lines) <= MAX_HEADING_LINES or len(block.inlines or []) > MAX_HEADING_LINES:
        return False
    if _is_monospace(block):
        return False
    text = block_text(block)
    if not _reads_as_title(text) or len(text.split()) > MAX_PRINTED_HEADING_WORDS:
        return False
    if text.rstrip().endswith((".", ",", ";")):
        return False
    apart = _stands_apart(lines, text, body)
    x0 = min(l["box"][0] for l in lines)
    x1 = max(l["box"][2] for l in lines)
    top, bottom = min(l["box"][1] for l in lines), max(l["box"][3] for l in lines)
    height = max(l["box"][3] - l["box"][1] for l in lines)
    if apart and _in_head_row(lines[0], others, body):
        return False
    if apart == "larger":
        return True
    if not under or under[0]["page"] != lines[0]["page"]:
        return False
    introduces = bool(apart) and (text.rstrip().endswith(":") or _in_head_row(under[0], others, body))
    if not introduces and (len(under) < 2 or _stands_apart([under[0]], under[0].get("text") or "", body)):
        return False
    utop = under[0]["box"][1]
    left = min(l["box"][0] for l in under)
    right = max(l["box"][2] for l in under)
    if not bottom <= utop <= bottom + MAX_HEADING_GAP_LINES * height:
        return False
    # hanging out to its left heads it whatever its print - "PUSH IX",
    # in capitals, clear of its text's left edge
    if x1 <= right and x0 < left - HANGING_INDENT_LINES * (bottom - top):
        return True
    return bool(apart) and left < x1 and x0 < right


def _in_head_row(line: Dict[str, Any], others: Sequence[Dict[str, Any]], body: float) -> bool:
    """Whether a line stands in a row of HEAD_ROW_CELLS lines or more that
    stand apart (_stands_apart) - a table's column heads."""
    top, bottom = line["box"][1], line["box"][3]

    def beside(other: Dict[str, Any]) -> bool:
        shared = min(bottom, other["box"][3]) - max(top, other["box"][1])
        return (other.get("page") == line.get("page")
                and shared >= SAME_ROW * min(bottom - top, other["box"][3] - other["box"][1]))

    mates = [o for o in others if o is not line and beside(o) and _stands_apart([o], o.get("text") or "", body)]
    return len(mates) >= HEAD_ROW_CELLS - 1


def _line_text(inline: Any) -> str:
    return " ".join(getattr(sp, "text", "") for sp in getattr(inline, "spans", []) or []).strip()


def columns(block: Any) -> List[List[Any]]:
    """A scanned page's block's lines in the columns they stand in, where
    OCR ran two columns' text into one block: lines side by side, apart
    across, fall in different columns - each COLUMN_LINES or more, one of
    them running text (COLUMN_WORDS). [] where its lines stand in one
    column."""
    inlines = [il for il in (block.inlines or [])
               if getattr(il, "visual_layout", None) is not None and il.visual_layout.bounding_box]
    if (not _printed(block) or len(inlines) != len(block.inlines or [])
            or len(inlines) < 2 * COLUMN_LINES):
        return []
    order = sorted(range(len(inlines)), key=lambda k: inlines[k].visual_layout.bounding_box.x0)
    groups: List[List[int]] = []
    right = None
    for k in order:
        box = inlines[k].visual_layout.bounding_box
        if right is None or box.x0 >= right:
            groups.append([])
            right = box.x1
        groups[-1].append(k)
        right = max(right, box.x1)

    def text_column(group: List[int]) -> bool:
        return (len(group) >= COLUMN_LINES
                and max(len(_line_text(inlines[k]).split()) for k in group) >= COLUMN_WORDS)

    if len(groups) < 2 or not all(text_column(g) for g in groups):
        return []
    return [[inlines[k] for k in sorted(g)] for g in groups]


def heading_runs(inlines: List[Any], printed: Dict[str, Dict[str, Any]], body: float) -> List[List[Any]]:
    """A scanned page's block's lines cut at the headings OCR ran into its
    body text: in pieces, a heading's line or two (MAX_HEADING_LINES)
    standing apart from the body (_stands_apart), reading as a title, a
    piece of its own - at the block's head (the Intel 3000 manual's
    "M-BUS AND I-BUS INPUTS The M-bus inputs..."), or after a line ending a
    sentence ("I/O devices. A AND B MULTIPLEXERS", "...M-bus. SCRATCHPAD The
    scratchpad..."). A heading's second line measured smaller - few
    capitals: "Incrementer" - goes with its first where printed in its
    weight and slant. inlines are a block's lines, or a column's of them
    (columns); printed, their print by their text. [] where none stands in
    them, or they all stand apart - a heading on its own."""
    if len(inlines) < 2 or not printed:
        return []
    lines = [printed.get(_line_text(il)) for il in inlines]
    apart = [bool(l) and bool(_stands_apart([l], l.get("text") or "", body)) for l in lines]
    if all(apart) or not any(apart):
        return []

    def goes_on(k: int) -> bool:
        before, line = lines[k - 1], lines[k]
        return (bool(before) and bool(line) and (line.get("bold") or line.get("italic"))
                and (line.get("bold"), line.get("italic")) == (before.get("bold"), before.get("italic"))
                and not _line_text(inlines[k - 1]).rstrip().endswith((".", ":")))

    cuts = []
    k = 0
    while k < len(inlines):
        if not apart[k]:
            k += 1
            continue
        end = k
        while end < len(inlines) and apart[end]:
            end += 1
        while end < len(inlines) and end - k < MAX_HEADING_LINES and goes_on(end):
            end += 1
        run_text = " ".join(_line_text(il) for il in inlines[k:end])
        opens = k == 0 or _line_text(inlines[k - 1]).rstrip().endswith((".", ":"))
        if (end - k <= MAX_HEADING_LINES and opens and _reads_as_title(run_text)
                and len(run_text.split()) <= MAX_PRINTED_HEADING_WORDS
                and not run_text.rstrip().endswith((".", ",", ";"))):
            cuts.append((k, end))
        k = end
    if not cuts:
        return []
    pieces, start = [], 0
    for k, end in cuts:
        if k > start:
            pieces.append(inlines[start:k])
        pieces.append(inlines[k:end])
        start = end
    if start < len(inlines):
        pieces.append(inlines[start:])
    return pieces if len(pieces) > 1 else []


def printed_levels(headings: List[Any], body: float) -> Dict[int, int]:
    """The levels of a scanned document's headings, by their print: a
    larger size higher - sizes within SAME_HEADING_SIZE of each other are
    one - and in one size capitals over lowercase, upright over italic.
    headings are blocks; the result maps id(block) to its level, from 1."""
    styled = []
    for block in headings:
        lines = _printed(block)
        styled.append((block, _printed_size(lines), _capitals(block_text(block)),
                       all(l.get("italic") for l in lines)))
    sizes = sorted({round(s, 2) for _, s, _, _ in styled}, reverse=True)
    rank: Dict[float, int] = {}
    k, low = -1, None
    for size in sizes:
        if low is None or size * SAME_HEADING_SIZE < low:
            k += 1
        rank[size] = k
        low = size
    keys = {id(b): (rank[round(s, 2)], not caps, italic) for b, s, caps, italic in styled}
    order = sorted(set(keys.values()))
    return {i: order.index(key) + 1 for i, key in keys.items()}


def _collect_containers(
    containers: List[ContainerUnit], result: List[ContainerUnit]
) -> None:
    for c in containers:
        result.append(c)
        child_containers = [ch for ch in c.children if isinstance(ch, ContainerUnit)]
        if child_containers:
            _collect_containers(child_containers, result)
