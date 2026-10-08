"""printed: what a line of a page looks like in print, read off its pixels.

Where its ink stands, its baseline, its type size, face, weight, slant,
colour and underline: what a page rebuilt where it was printed needs
(RFC 0021 §3, positional render), and what neither OCR nor a scan's text
layer says - tesseract boxes a line by its own guess and sizes it from
that box, and calls nothing bold, italic, blue or underlined.

measure_line reads one line's facts; settle_page decides, from all the
lines of a page together, the face and weight each is set in - one line
alone is too short to tell a bold from a heavily printed regular, or a
grotesque from a roman. A line is measured as the builder will set it:
the faces compared with its print are the base-14 counterparts of the
TeX Gyre faces the builder sets (Termes, Heros, Cursor) - and Schola, a
Century Schoolbook with no base-14 counterpart, itself - and its size is
its capitals' or ascenders' height over the share of the size they reach
in that face.
"""

import functools
import re
import statistics
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from src.adapters.pdf_adapter import _measure_stroke_pt


# Faces a line's text is set in to be compared with its print - base-14
# names, or a TeX Gyre file where base-14 has no counterpart: (regular,
# bold, italic, bold italic). A book set in Century Schoolbook (the
# paragraph fixture B) came back in Times, narrower, its x-height lower.
FACES = {
    "serif": ("tiro", "tibo", "tiit", "tibi"),
    "sans": ("helv", "hebo", "heit", "hebi"),
    "mono": ("cour", "cobo", "coit", "cobi"),
    "schoolbook": ("texgyreschola-regular.otf", "texgyreschola-bold.otf",
                   "texgyreschola-italic.otf", "texgyreschola-bolditalic.otf"),
}
# What the builder's faces reach over their size, measured on the TeX Gyre
# files: capitals ("H") and lowercase ascenders ("d").
CAP_EM = {"serif": 0.662, "sans": 0.728, "mono": 0.562, "schoolbook": 0.722}
ASCENDER_EM = {"serif": 0.682, "sans": 0.728, "mono": 0.602, "schoolbook": 0.738}
_ASCENDERS = set("bdfhkl")  # a "t" stands short of them, an "i"'s dot prints faint
# Their strokes over their size, as pdf_adapter._measure_stroke_pt measures
# a print: (regular, bold) upright and (regular, bold) italic. Schola's read
# at 20pt (0.100, 0.163) and (0.087, 0.156), scaled as Termes' read there
# (0.087, 0.144), (0.075, 0.119) stand to its own.
STROKE_EM = {
    "serif": ((0.094, 0.144), (0.081, 0.125)),
    "sans": ((0.094, 0.150), (0.094, 0.150)),
    "mono": ((0.044, 0.119), (0.044, 0.119)),
    "schoolbook": ((0.108, 0.163), (0.094, 0.164)),
}
_FACE_MIN_LETTERS = 6     # a line this long votes for its page's face
_WEIGHT_MIN_LETTERS = 4   # a line this long says what the page's regular weight is
_SKEW_MIN_PT = 80.0       # a line this wide says how its stretch of the page is skewed
_SKEW_PART = 3.0          # of a line's ink height, how wide a stretch its skew is read from the baseline of
_SKEW_INKED = 0.5         # of a line's ink across, the least a stretch holds to have a baseline
_SKEW_NEAR = 11           # the lines of a column, itself among them, a line's skew is the middle of
_SAME_SIZE = 0.1          # within this of its kind's usual size, a line is set at it
_SHORT_TOKEN = 3          # characters in a token too short to measure its size by
_SAME_ROW = 0.5           # of the lower box's height two source boxes share on one row
_BOLD_GAIN = 0.6          # of the gap from regular to bold, over the page's lightest
# Of the text's around it, a word's weight in a bold run of a regular line:
# on the paragraph fixture D regular words weigh 0.61-0.80pt (usual 0.71),
# bold ones 0.90-1.07.
_WORD_BOLD = 1.2
# Of the lines' around it in its column, and of its page's usual, the
# weight of a line's words, in the middle, where the line is bold - and a
# word of a bold line is, where it weighs so much: on the heading and
# paragraph fixtures regular lines stand within 1.07 of the lines around
# them and 1.09 of their page, bold ones at 1.11 and over of both (the
# MCS-40 manual's product lines, a bold lighter than most, 1.20-1.28 and
# 1.13-1.22). Weighed against its page alone a line in a stretch a scan
# printed heavier came out bold; against the lines around it alone, one
# over a list set smaller and lighter (the Signetics 8080 manual's "The
# move is completed with the microinstruction fields:", 1.18 and 1.07).
_LINE_BOLD = 1.1
_AROUND_LINES = 8.0       # its own heights up and down, the lines around a line stand within
_AROUND_WORDS = 3         # words weighed a line takes to say what the text around another weighs
_AROUND_MIN = 3           # lines around a line it takes to weigh it by them; fewer, by the page's usual
_BODY_CHARS = 40          # a line this long is body text, its words the page's usual weights
_WEIGHT_MIN_WORDS = 5     # words of a kind it takes to say what the page's usual weight of it is
_WORD_MIN_GLYPHS = 3      # letters and figures a word takes to be weighed on its own ("be" goes with its neighbour)
# Capitals' and figures' weight over lowercase's, where the body has too
# few to say: 1.04-1.10 in the fixtures' body lines.
_CAPITALS_WEIGHT = 1.08
_STEMS = set("bdhiklmnpqrtuBDEFHIKLMNPRTU")  # letters with an upright stem to lean

ITALIC_SLANT = 0.12       # tan of the lean; an italic leans 0.2 or so
_INK_LEVEL = 160          # 0-255 grey below which a pixel is ink, for face likeness
_GLYPH_CONTRAST = 120     # summed RGB difference from what a glyph is printed on
_RULE_SPAN = 0.9          # a row this full of ink is a rule crossing the line
_UNDERLINE_SPAN = 0.8     # a rule under the line covering this much of it underlines it
_BASELINE_BODY = 0.5      # a row this dense against the line's densest is in its body, over its baseline
# of a line's box height: the widest gap between two letters of a word -
# the paragraph fixture D's "c" and "h" of "each" stand 0.83pt apart at 8pt
_LETTER_GAP = 0.15
_BODY_TOP = 0.3           # of its capitals' height under their top, a line's lowercase body starts (x-height ~0.72)
_HEAD_DENSITY = 0.08      # a row this dense against the line's densest is its capitals', not a stray descender
_COLOUR_SPREAD = 80       # channels this far apart: printed in a colour, not black
_MISREAD = 0.5            # of a word's and its set text's ink, the most one misses of the other
_LOWERED = 0.15           # of a line's capitals' height, how far under its baseline a letter set lower reaches
_DESCENDING = set("gjpqy()[]{},;|/_")  # what reaches as far under a baseline, set in the line
# - and of a word of signs alone, no letter or figure in it: OCR takes one
# sign for another most of all, an arrow for a dash ("(SP-2) <- IXL" read
# "(SP—2) — IXz", the dash missing 0.46 of the arrow), and no reader reads
# a sign for its text
_MISREAD_SIGN = 0.3
_OVERLINE_REACH = 0.35    # of a line's ink height: how far over its top an overline stands
_OVERLINE_DIP = 0.1       # of it: how far under its top - an overline is its topmost ink, a hyphen is not
_OVERLINE_MIN = 0.4       # of a line's ink height: the shortest overline, over one capital
_OVERLINE_THICK = 0.15    # of a line's ink height: the thickest
_OVERLINE_CLEAR = 0.2     # of its length, the most ink a row over an overline holds (a descender through it)
_TALL = 0.1               # of a line's ink height, how far over most of its letters' tops its capitals' and ascenders' stand
_DARK_SHARE = 0.5         # of a line's ink, the least it prints dark to be measured by its dark ink
_OVER_CAPS = 0.25         # of a line's capitals' height, how far over their tops only the line above's ink stands
_OVER_TOPS = 0.05         # of it, how far over their tops a bar's middle stands, a capital's own top short of it
_NAME_COVER = 0.34        # of a name's width, more than an overline over it reaches over
_ZOOM = 6.0
_FIT_ZOOM = 12.0          # a line's set words are laid over its print at (_fit_baseline)
_FIT_REACH = 0.4          # pt: the furthest its baseline is moved
_FIT_MIN_WORDS = 3        # a line of fewer words is too little to lay over its print
_FIT_MIN_LIKENESS = 0.3   # the least its set words' darkness correlates with the print's


def _thickened(np, mask):
    """A mask grown by a pixel each way, so strokes a pixel apart still meet."""
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= out[:, :-1].copy()
    out[:, :-1] |= out[:, 1:].copy()
    return out


def ink_mask(np, pix):
    """A pixmap's ink, cut to the ink's own bounding box (None if none)."""
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    ink = grey < _INK_LEVEL
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if not len(rows) or not len(cols):
        return None
    return ink[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


@functools.lru_cache(maxsize=None)
def _font_file(name: str) -> Optional[str]:
    """A TeX Gyre file's path, where TeX is installed (kpsewhich)."""
    try:
        path = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return path or None


def likeness(np, pymupdf, print_mask, text: str, fontname: str) -> float:
    """How well text set in fontname - a base-14 name or a font file
    (FACES) - covers the print: the overlap of their ink, each cut to its
    own extent and scaled onto the print's. 0 where the file is missing."""
    doc = pymupdf.open()
    page = doc.new_page(width=40 * len(text) + 40, height=80)
    if fontname.endswith(".otf"):
        path = _font_file(fontname)
        if not path:
            doc.close()
            return 0.0
        page.insert_font(fontname="F", fontfile=path)
        fontname = "F"
    page.insert_text((10, 50), text, fontsize=30, fontname=fontname)
    mask = ink_mask(np, page.get_pixmap())
    doc.close()
    if mask is None:
        return 0.0
    h, w = print_mask.shape
    scaled = mask[(np.arange(h) * mask.shape[0] // h)][:, (np.arange(w) * mask.shape[1] // w)]
    a, b = _thickened(np, print_mask), _thickened(np, scaled)
    return float((a & b).sum()) / max(1, float((a | b).sum()))


def slant(np, ink) -> float:
    """How far a block of ink leans right, as the shear that stands its
    strokes upright: the one that piles the ink into the fewest columns."""
    ys, xs = np.nonzero(ink)
    ys = ys - ys.mean()
    best, best_score = 0.0, -1.0
    for shear in np.linspace(-0.1, 0.4, 26):
        cols = np.round(xs + shear * ys).astype(int)
        score = float((np.bincount(cols - cols.min()) ** 2).sum())
        if score > best_score:
            best, best_score = float(shear), score
    return best


def _rows_through(np, rows, middle: int):
    """The run of True rows through middle, or the nearest run to it."""
    if not rows[middle]:
        near = np.flatnonzero(rows)
        if not len(near):
            return None
        middle = int(near[np.abs(near - middle).argmin()])
    top, bottom = middle, middle
    while top > 0 and rows[top - 1]:
        top -= 1
    while bottom < len(rows) - 1 and rows[bottom + 1]:
        bottom += 1
    return top, bottom


_BOX_CORE = 0.2           # of a box's height in from each edge: surely its own line
_LINE_GAP_SHARE = 0.15    # a row this light against the line's own is between lines


def _own_rows(np, glyphs, run, rect, clip):
    """The rows of a line's own ink, out of the run of inked rows through
    it: lines set close or askew touch, and the run goes on into the next
    one. It is cut at its lightest row past the source box's edge, where
    one line ends and the next begins, when that row is light against
    the line's own."""
    top, bottom = run
    density = glyphs.sum(axis=1)
    core_lo = int((rect.y0 + rect.height * _BOX_CORE - clip.y0) * _ZOOM)
    core_hi = int((rect.y1 - rect.height * _BOX_CORE - clip.y0) * _ZOOM)
    core = density[max(core_lo, top):min(core_hi, bottom) + 1]
    light = _LINE_GAP_SHARE * (float(np.median(core)) if len(core) else 0.0)
    if bottom > core_hi + 1:
        seam = core_hi + 1 + int(np.argmin(density[core_hi + 1:bottom + 1]))
        if density[seam] <= light:
            bottom = seam - 1
    if top < core_lo - 1 and core_lo > 0:
        seam = top + int(np.argmin(density[top:core_lo]))
        if density[seam] <= light:
            top = seam + 1
    return (top, bottom) if top <= bottom else run


def _foot(np, band) -> int:
    """A line's baseline row: the last its ink fills to _BASELINE_BODY of
    its densest row or more - the bottom of its body, a scan's blur half
    through its fall into the descenders. Down from its densest row to the
    first the ink falls away under for good, a line of many "p"s and "y"s
    - their tails as dense under it as a fraction of its body - set its
    baseline a point into them."""
    return int(np.flatnonzero(band >= _BASELINE_BODY * band.max())[-1])


def _foot_and_head(np, band):
    """A line's baseline row (_foot) and its capitals' top: where
    the unbroken ink over the baseline starts, from the first row its
    capitals and ascenders fill (a descender or two from the line above
    fill less). (None, None) where there is no ink."""
    if not len(band) or band.max() == 0:
        return None, None
    foot = _foot(np, band)
    head = foot
    while head > 0 and band[head - 1] > 0:
        head -= 1
    while head < foot and band[head] < _HEAD_DENSITY * band.max():
        head += 1
    return foot, head


def _stretch_feet(np, region) -> List[Any]:
    """The baseline row (_foot) of each stretch of a line, _SKEW_PART line
    heights wide, as (its middle column, the row): a stretch of a word
    space, a dash or a comma has none."""
    h, w = region.shape
    part = max(2, int(_SKEW_PART * h))
    density = region.mean(axis=0)
    feet = []
    for a in range(0, w - part // 2, part):
        if density[a:a + part].mean() < _SKEW_INKED * density.mean():
            continue
        feet.append((a + min(part, w - a) / 2.0, float(_foot(np, region[:, a:a + part].mean(axis=1)))))
    return feet


def _skew(np, region) -> float:
    """How far a line's baseline falls over its width (dy/dx): the middle
    of the falls between the baselines of its stretches (_stretch_feet) a
    third of the line or more apart. A scan's pixel, a third of a point,
    puts a stretch's foot a row or two off: read from the feet of its
    thirds alone, a column's lines came out skewed from 0 to 0.006 where
    all fell 0.004."""
    feet = _stretch_feet(np, region)
    w = region.shape[1]
    falls = [(f1 - f0) / (x1 - x0) for k, (x0, f0) in enumerate(feet) for x1, f1 in feet[k + 1:]
             if x1 - x0 >= w / 3.0]
    return float(np.median(falls)) if falls else 0.0


def _lift(skew: float, width: int) -> int:
    """How far down a straightened line's rows are set: room for the
    columns a falling line moves up."""
    return int(round(max(0.0, skew * width)))


def _straightened(np, region, skew: float):
    """A line's ink with each column moved up by its fall, so the line
    stands straight at its left edge's height."""
    h, w = region.shape
    lift = _lift(skew, w)
    out = np.zeros((h + int(round(abs(skew) * w)) + 1, w), dtype=bool)
    for x in range(w):
        shift = lift - int(round(skew * x))
        lo = max(0, shift)
        src_lo = max(0, -shift)
        n = min(h - src_lo, out.shape[0] - lo)
        if n > 0:
            out[lo:lo + n, x] = region[src_lo:src_lo + n, x]
    return out


def _overlines(np, glyphs, top: int, bottom: int, left: int, right: int, head: int,
               fall: int = 0) -> List[Any]:
    """Rules drawn over a line's letters - a signal active low, "RAS" with
    a bar over it - as (first row, last row, first column, end column): a
    few thin rows inked along in one run, all but clear over it and joined
    to nothing over it (the bottom of a letter of the line above is),
    standing clear of the letters under it, where a capital's own top runs
    on down into its letter (_runs_on) - or, a scan's blur joining it to
    them, standing above the tops of the line's letters read beside the
    bars, the line stood straight. They are looked for about head, the row
    the line's capitals start at at its left edge - the line's first inked
    row can be a descender's tip from the line above - and as far further
    as the line falls (fall, rows) over its width."""
    h = bottom - top + 1
    rows = glyphs.shape[0]
    thick = max(1, int(round(_OVERLINE_THICK * h)))
    min_len = max(3, int(_OVERLINE_MIN * h))
    bars: List[Any] = []
    seen = np.zeros(glyphs.shape, dtype=bool)
    lo_row = head - int(_OVERLINE_REACH * h) + min(0, fall)
    hi_row = head + int(_OVERLINE_DIP * h) + max(0, fall)
    for r in range(max(0, lo_row), min(rows, hi_row + 1)):
        line = np.concatenate(([False], glyphs[r, left:right], [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(line))
        for a, b in zip(edges[::2] + left, edges[1::2] + left):
            if b - a < min_len or seen[r, a:b].any():
                continue
            end = r
            while end + 1 < rows and glyphs[end + 1, a:b].mean() >= 0.8:
                end += 1
            # over it, a row all but clear along it: the bottom of the line
            # above's letters has their sides over it
            above = range(max(0, r - 1 - thick), r)
            if end + 1 - r <= thick and any(glyphs[q, a:b].mean() <= _OVERLINE_CLEAR for q in above):
                band = glyphs[:, left:right]
                # the bottom of a letter of the line above runs on up
                if _runs_on(np, band[::-1], rows - 1 - end, rows - 1 - r, a - left, b - left, thick):
                    continue
                apart = not _runs_on(np, band, r, end, a - left, b - left, thick)
                bars.append((r, end, int(a), int(b), apart))
                # its fainter rows under it are the same bar
                seen[r:end + 2 + thick, a:b] = True
    if not bars:
        return []
    # the tops of the line's letters, read where no bar stands, the line
    # stood straight - askew, a falling line's letters at its left stand
    # over a bar at its right: where its capitals and ascenders stand, the
    # middle of the tops of its columns standing over most (_TALL) - most
    # stand only as high as its lowercase; with none, where most stand
    rest = glyphs[top:bottom + 1, left:right].copy()
    for _, _, a, b, _ in bars:
        rest[:, a - left:b - left] = False
    width = max(1, right - left)
    skew = fall / width
    straight = _straightened(np, rest, skew)
    heads = np.argmax(straight[:, straight.any(axis=0)], axis=0)
    tops: Optional[float] = None
    if len(heads):
        most = float(np.median(heads))
        tall = heads[heads < most - _TALL * h]
        tops = float(np.median(tall)) if len(tall) >= thick else most

    def over_tops(r: int, end: int, a: int, b: int) -> bool:
        # its middle row well over them (_OVER_TOPS) - a scan's blur
        # thickens a bar down into them, and a capital's own top hangs
        # from them; nothing beside - barred words alone, or figures alone
        # ("3 7 7") - and only a bar clear of what is under it stands over
        upright = (r + end) / 2.0 - top + _lift(skew, width) - int(round(skew * ((a + b) / 2 - left)))
        return tops is not None and upright < tops - _OVER_TOPS * h

    accepted = sorted(((r, end, a, b) for r, end, a, b, apart in bars if apart or over_tops(r, end, a, b)),
                      key=lambda bar: bar[2])
    # a bar the scan broke - its pieces on the same rows (a falling line's
    # bar falls along it), a gap of a stroke or two between - is one bar
    joined: List[Any] = []
    for r, end, a, b in accepted:
        if joined and a - joined[-1][3] <= 2 * thick and abs(r - joined[-1][0]) <= thick:
            r0, e0, a0, b0 = joined[-1]
            joined[-1] = (min(r0, r), max(e0, end), a0, max(b0, b))
        else:
            joined.append((r, end, a, b))
    return joined


def _over_names(a: int, b: int, words: List[Any]) -> Optional[Any]:
    """The names a bar from column a to b stands over - words (first
    column, end column, text) under it - and so the columns it spans: a
    bar negates a signal's name, all of it ("RAS", "W", the "RAS" of
    "RAS-only"), and where a faint scan kept only part of it, it reaches
    over more than a part of the name (_NAME_COVER) and is drawn over all
    of it. None where it stands over no name: a capital's top a faint scan
    tore off its letter stands over a letter of a word (the "R" of
    "Repeat"), or over a figure ("6.")."""
    span = None
    for x0, x1, text in words:
        if not text or x1 <= a or x0 >= b:
            continue
        for run in re.finditer(r"[^\W_]+", text):
            # its letters taken as wide as one another
            s = x0 + (x1 - x0) * run.start() / len(text)
            e = x0 + (x1 - x0) * run.end() / len(text)
            if min(e, b) - max(s, a) > _NAME_COVER * (e - s) and any(ch.isalpha() for ch in run.group()):
                span = (min(a, s, span[0] if span else a), max(b, e, span[1] if span else b))
    return span


def _joined(np, ink, seed):
    """The ink joined, a pixel to the next, to seed (a mask of ink's shape),
    as a mask of ink's shape."""
    grown = seed & ink
    while True:
        spread = grown.copy()
        spread[1:] |= grown[:-1]
        spread[:-1] |= grown[1:]
        wide = spread.copy()
        wide[:, 1:] |= spread[:, :-1]
        wide[:, :-1] |= spread[:, 1:]
        wide &= ink
        if (wide == grown).all():
            return grown
        grown = wide


def _runs_on(np, glyphs, r: int, end: int, a: int, b: int, thick: int) -> bool:
    """Whether the ink of a run (rows r to end, columns a to b) runs on down
    into a letter - joined, a pixel to the next, to ink more than thick
    rows under it, within twice thick columns to either side: a capital's
    own top ("T"'s stem, an "O"'s or a "3"'s curve on down), or a bar the
    blur joins to the letters under it. Turned upside down (glyphs[::-1]),
    whether it runs on up: the bottom of a letter of the line above."""
    rows, cols = glyphs.shape
    lo, hi, last = max(0, a - 2 * thick), min(cols, b + 2 * thick), min(rows - 1, end + 1 + thick)
    window = glyphs[r:last + 1, lo:hi]
    seen = np.zeros_like(window)
    seen[:end + 1 - r, a - lo:b - lo] = window[:end + 1 - r, a - lo:b - lo]
    while True:
        grown = seen.copy()
        grown[1:] |= seen[:-1]
        grown[:-1] |= seen[1:]
        spread = grown.copy()
        spread[:, 1:] |= grown[:, :-1]
        spread[:, :-1] |= grown[:, 1:]
        spread &= window
        if spread[-1].any():
            return True
        if (spread == seen).all():
            return False
        seen = spread


def _weight_of(np, ink) -> float:
    """How thick ink's strokes are, in pixels: twice its area over its
    outline. Unlike a median run across the strokes it does not step by
    whole pixels - a scan's strokes are three of them wide."""
    padded = np.pad(ink, 1)
    outline = int((padded[1:, :] != padded[:-1, :]).sum() + (padded[:, 1:] != padded[:, :-1]).sum())
    return 2.0 * float(ink.sum()) / outline if outline else 0.0


def _glyph_spans(np, ink) -> List[Any]:
    """A word's ink falling apart across: the runs of columns it inks, a
    clear column between two."""
    cols = np.concatenate(([False], ink.any(axis=0), [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(cols))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]


def _word_inks(np, region, body, words, x_of, gap: int) -> List[List[Any]]:
    """Where each word of a line prints: its ink's left and right column in
    region (x_of turns a page point into a region column). OCR boxes a word
    by its own guess - short of a glyph, or over a letter of the next - so
    the words are read off the ink: its lowercase body (body: those rows'
    ink by column, which no "f" hook or "y" tail overhangs a space through)
    falls into runs of letters, apart where a gap is wider than gap columns:
    as many runs as words, each the next word's; else each run goes to the
    word whose box holds its middle, and a run two boxes hold is cut at its
    widest gap between them. A word's edges are its runs' ink in all its
    rows, short of the space to either neighbour - cut at its widest column
    clear in all rows (a closing quote over the body runs on past the
    space's middle), at its middle where none is (an "f" hook over it); a
    word no run goes to is left out."""
    inked = region.any(axis=0)
    w = len(inked)
    cols = np.flatnonzero(body)
    if not len(cols):
        return []
    runs = []
    start = prev = int(cols[0])
    for c in cols[1:]:
        if c - prev > gap + 1:
            runs.append([start, prev + 1])
            start = int(c)
        prev = int(c)
    runs.append([start, prev + 1])
    boxes = [(int(round(x_of(wd[0]))), int(round(x_of(wd[2]))), wd[4]) for wd in sorted(words, key=lambda wd: wd[0])]

    def holder(x: float) -> Optional[int]:
        inside = [k for k, (a, b, _) in enumerate(boxes) if a <= x < b]
        if inside:
            return inside[0]
        near = min(range(len(boxes)), key=lambda k: min(abs(x - boxes[k][0]), abs(x - boxes[k][1])), default=None)
        return near

    owned: Dict[int, List[int]] = {}
    if len(runs) == len(boxes):
        # as many runs as words: each the next one's, whatever OCR's boxes
        # (the paragraph fixture D's "system" boxed over the next word's "f")
        for k, (lo, hi) in enumerate(runs):
            owned[k] = [lo, hi]
        runs = []
    for lo, hi in runs:
        held = sorted({k for k, (a, b, _) in enumerate(boxes) if a < hi and lo < b and (a + b) / 2 >= lo - gap and (a + b) / 2 < hi + gap})
        if len(held) > 1:
            # one run, two words' boxes: cut at its widest gap near each seam
            cuts = []
            for k0, k1 in zip(held, held[1:]):
                seam = (boxes[k0][1] + boxes[k1][0]) // 2
                lo_s, hi_s = max(lo + 1, seam - 2 * gap), min(hi - 1, seam + 2 * gap)
                # the widest gap there - a word space, if narrow - at its middle
                gaps, start = [], None
                for c in range(lo_s, hi_s + 1):
                    if c < hi_s and not body[c]:
                        start = c if start is None else start
                    elif start is not None:
                        gaps.append((start, c))
                        start = None
                if gaps:
                    a, b = max(gaps, key=lambda g: (g[1] - g[0], -abs((g[0] + g[1]) / 2 - seam)))
                    cuts.append((a + b) // 2)
                else:
                    cuts.append(seam)
            edges = [lo] + cuts + [hi]
            for k, a, b in zip(held, edges, edges[1:]):
                owned.setdefault(k, []).extend([a, b])
            continue
        k = holder((lo + hi) / 2)
        if k is not None:
            owned.setdefault(k, []).extend([lo, hi])
    spans = [[min(owned[k]), max(owned[k]), boxes[k][2]] for k in sorted(owned)]

    def space(a: int, b: int) -> int:
        """Where the space between a word's body ending at a and the next's
        starting at b is cut."""
        clear = np.concatenate(([False], ~inked[a:b], [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(clear))
        gaps = list(zip(edges[::2], edges[1::2]))
        if not gaps:
            return (a + b) // 2
        g0, g1 = max(gaps, key=lambda g: g[1] - g[0])
        return a + int(g0 + g1) // 2

    out = []
    for k, (lo, hi, text) in enumerate(spans):
        left = space(spans[k - 1][1], lo) if k > 0 else 0
        right = space(hi, spans[k + 1][0]) if k + 1 < len(spans) else w
        full = np.flatnonzero(inked[left:right])
        if len(full):
            lo, hi = min(lo, left + int(full[0])), max(hi, left + int(full[-1]) + 1)
        out.append([lo, hi, text])
    return out


def measure_line(np, pymupdf, page, rect, text: str, words: Optional[List[Any]] = None,
                 skew: Optional[float] = None) -> Optional[Dict[str, Any]]:

    """The print of one line, boxed (in points) at rect by its source - at
    the skew given, else at its own (_skew).

    Returns, in points on the page: "box" [x0, y0, x1, y1] - the line's
    ink; "baseline" - at its left ink edge, and "skew" - how far it falls
    over its length (dy/dx); "height" - from its capitals' top to the
    baseline;
    "stroke" - its strokes' median width; "italic" (and "slant", the lean
    it was judged by); "scores" - how well each face covers it, regular
    and bold, upright or italic as it leans; "rgb" - its colour where it
    is not black; "underline" [y, thickness] where a rule runs under it;
    "overlines" [[x0, x1, y, thickness]] where rules stand over its words.
    None where the box holds no ink.
    """
    pad_y = rect.height / 2.0
    clip = pymupdf.Rect(rect.x0 - 2, rect.y0 - pad_y, rect.x1 + 2, rect.y1 + pad_y) & page.rect
    if clip.is_empty:
        return None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_ZOOM, _ZOOM), clip=clip)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
    ground = np.median(rgb.reshape(-1, 3), axis=0)
    ink = (np.abs(rgb - ground).sum(axis=2) > _GLYPH_CONTRAST) & (rgb.sum(axis=2) < ground.sum())
    # the ink as the overlay reads it - how much of the page the line darkens
    dark = (rgb.mean(axis=2) < _INK_LEVEL) & ink
    ruled = ink.mean(axis=1) > _RULE_SPAN
    glyphs = ink.copy()
    glyphs[ruled, :] = False
    glyphs[:, ink.mean(axis=0) > _RULE_SPAN] = False
    middle = min(max(int(((rect.y0 + rect.y1) / 2 - clip.y0) * _ZOOM), 0), pix.height - 1)
    run = _rows_through(np, glyphs.any(axis=1), middle)
    if run is None:
        return None
    top, bottom = _own_rows(np, glyphs, run, rect, clip)
    cols = np.flatnonzero(glyphs[top:bottom + 1].any(axis=0))
    if not len(cols):
        return None
    left, right = int(cols[0]), int(cols[-1]) + 1
    mask = glyphs[top:bottom + 1, left:right]
    # A scan stands its lines askew, several points over a long one: the
    # line is stood straight by its skew, and its baseline and capitals'
    # top are read off the straightened ink - askew, they smear over the
    # fall - where it prints dark: a scan's blur stands a faint fringe
    # round each glyph, a row or two under its foot and over its top, and
    # read off it, a line's baseline stood a fifth of a point low, its
    # capitals as much too tall.
    region = glyphs[top:bottom + 1, left:right]
    if skew is None:
        skew = _skew(np, region)
    upright = _straightened(np, region, skew)
    deep = _straightened(np, dark[top:bottom + 1, left:right], skew)
    # a line printed light - in colour, or grey - has little dark ink
    foot, head = _foot_and_head(np, (deep if deep.sum() >= _DARK_SHARE * upright.sum() else upright).mean(axis=1))
    if foot is None:
        return None
    # the straightened rows are the line's at its left edge
    base = top + foot + 1.0 - _lift(skew, right - left)
    height = float(foot + 1 - head)

    def pt_x(px: float) -> float:
        return clip.x0 + px / _ZOOM

    def pt_y(px: float) -> float:
        return clip.y0 + px / _ZOOM

    # A rule over a word or two: an overline, drawn as its own ink - laid
    # by the face, it would weigh the word down.
    bars = _overlines(np, glyphs, top, bottom, left, right, top + head - _lift(skew, right - left),
                      int(round(skew * (right - left))))

    # where each word prints (region columns), its bars' ink no part of it -
    # a bar over "RAS" reaches over the space before it: from the lowercase
    # body, straightened - from under the x-height, the arches of "m" and
    # "n" in it, else an "m" falls apart into stems a word space apart - to
    # the baseline
    lettered = region.copy()
    fainter = max(1, int(round(_OVERLINE_THICK * (bottom - top + 1))))
    for r0, r1, a, b in bars:
        # with its fainter rows under it and its fainter ends
        lettered[max(0, r0 - top):max(0, r1 + 1 + fainter - top),
                 max(0, a - fainter - left):b + fainter - left] = False
    # stood straight, and none of the line above's descenders over its
    # capitals - a "g" of it hung over the space before "RAS"
    lettered = _straightened(np, lettered, skew)
    # what stands well over its capitals' tops (_OVER_CAPS) is the line
    # above's, and what hangs on down from it too - not a capital whose
    # blur reaches a row over its top
    above = np.zeros_like(lettered)
    above[:max(0, head - int(_OVER_CAPS * (foot - head)))] = True
    lettered &= ~_joined(np, lettered, lettered & above)
    inks = _word_inks(np, lettered, upright[head + int(_BODY_TOP * (foot - head)):foot + 1].any(axis=0),
                      words, lambda x: (x - clip.x0) * _ZOOM - left,
                      max(1, int(rect.height * _ZOOM * _LETTER_GAP))) if words else []

    # each bar over the names it stands over (_over_names)
    spans = [_over_names(a - left, b - left, inks) if words else (a - left, b - left) for _, _, a, b in bars]
    bars, spans = [bar for bar, span in zip(bars, spans) if span], [span for span in spans if span]
    # each as thick as it prints dark - a scan prints a thin bar grey, and
    # most of what stands out of the paper is no ink to the eye
    overlines = []
    for (r0, r1, a, b), (x0, x1) in zip(bars, spans):
        seen = [q for q in range(r0, r1 + 1) if dark[q, a:b].mean() >= 0.5]
        if seen:
            overlines.append([pt_x(left + x0), pt_x(left + x1), pt_y((seen[0] + seen[-1] + 1) / 2.0), len(seen) / _ZOOM])
        dark[r0:r1 + 1, a:b] = False

    # A rule just under the line, across most of it, underlines it (a link).
    underline = None
    for r in range(bottom + 1, min(pix.height, bottom + 1 + int(rect.height * _ZOOM / 2))):
        if ink[r, left:right].mean() >= _UNDERLINE_SPAN:
            end = r
            while end + 1 < pix.height and ink[end + 1, left:right].mean() >= _UNDERLINE_SPAN:
                end += 1
            underline = [pt_y((r + end + 1) / 2.0), (end + 1 - r) / _ZOOM]
            break

    lean = slant(np, mask)
    variant = 2 if lean >= ITALIC_SLANT else 0
    scores = {
        name: [likeness(np, pymupdf, mask, text.strip(), variants[variant + w]) for w in (0, 1)]
        for name, variants in FACES.items()
    } if text.strip() else {}

    pixels = rgb[top:bottom + 1, left:right][mask]
    colour = None
    if len(pixels):
        med = np.median(pixels, axis=0)
        if med.max() - med.min() > _COLOUR_SPREAD:
            colour = [int(v) for v in med]

    placed = []
    marks = []
    # Each word's own weight and lean, beside its line's: a bold or italic
    # word in a regular line ("refreshed", "algorithm"); and its ink itself,
    # for a word its text does not draw (read_printed_lines).
    for a, b, t in inks:
        own = dark[top:bottom + 1, left + a:left + b]
        facts = {"weight": _weight_of(np, own) / _ZOOM,
                 "slant": slant(np, region[:, a:b]) if region[:, a:b].any() else 0.0}
        # where its ink falls apart across - a letter each, or letters
        # run together, or a letter in pieces: the builder matches its
        # letters to them
        spans = _glyph_spans(np, own)
        if len(spans) > 1:
            facts["glyphs"] = [[pt_x(left + a + g0), pt_x(left + a + g1)] for g0, g1 in spans]
        placed.append([pt_x(left + a), pt_x(left + b), t, float(own.sum()) / _ZOOM ** 2, facts])
        marks.append((own, pt_x(left + a), pt_y(top)))

    return {
        "source": [rect.x0, rect.y0, rect.x1, rect.y1],
        "words": placed,
        "box": [pt_x(left), pt_y(min([top] + [bar[0] for bar in bars])), pt_x(right), pt_y(bottom + 1)],
        "baseline": pt_y(base),
        "skew": skew,
        "height": height / _ZOOM,
        "stroke": _measure_stroke_pt(page, pymupdf.Rect(pt_x(left), pt_y(top), pt_x(right), pt_y(bottom + 1))) or 0.0,
        "area": float(dark[top:bottom + 1, left:right].sum()) / _ZOOM ** 2,
        "italic": lean >= ITALIC_SLANT,
        "slant": lean,
        "scores": scores,
        "rgb": colour,
        "underline": underline,
        "overlines": overlines,
        "marks": marks,
    }


def size_in(face: str, height: float, text: str) -> float:
    """The type size whose capitals - or, in a line of lowercase,
    ascenders - stand height tall in face; 0 for a line of neither, whose
    height says nothing of its size."""
    tall = any(ch in _ASCENDERS for ch in text)
    capitals = any(ch.isupper() or ch.isdigit() for ch in text)
    if not tall and not capitals:
        return 0.0
    return height / (ASCENDER_EM[face] if tall and not capitals else CAP_EM[face])


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def _settled_skews(lines: List[Dict[str, Any]]) -> List[float]:
    """The skew each of a page's measured lines is set at. A column's lines
    were scanned together: a long line's skew is the middle of its own and
    its nearest neighbours' in its column (_SKEW_NEAR) - read alone, from a
    few stretches of it, one came out level where all its column fell
    0.004. A short line's skew is its few glyphs' own: it takes the skew of
    the nearest long line in its column, scanned with it."""
    long_lines = [l for l in lines if l["box"][2] - l["box"][0] >= _SKEW_MIN_PT]

    def column_of(line) -> List[Dict[str, Any]]:
        def shared(other) -> float:
            return min(line["box"][2], other["box"][2]) - max(line["box"][0], other["box"][0])
        mates = [l for l in long_lines if shared(l) > 0.5 * min(line["box"][2] - line["box"][0],
                                                                 l["box"][2] - l["box"][0])]
        return sorted(mates, key=lambda l: abs(l["baseline"] - line["baseline"]))[:_SKEW_NEAR]

    def apart(line, other) -> Tuple[bool, float]:
        beside = other["box"][2] <= line["box"][0] or line["box"][2] <= other["box"][0]
        return beside, abs(other["baseline"] - line["baseline"])

    settled = {id(l): statistics.median(m["skew"] for m in column_of(l)) for l in long_lines}
    skews = []
    for line in lines:
        if line["box"][2] - line["box"][0] >= _SKEW_MIN_PT:
            skews.append(settled[id(line)])
            continue
        # the nearest long line in its own column
        near = min(long_lines, key=lambda l: apart(line, l), default=None)
        skews.append(settled[id(near)] if near is not None else 0.0)
    return skews


def settle_page(lines: List[Dict[str, Any]]) -> None:
    """Decide, for the measured lines of one page (measure_line, each with
    its "text"), the type each is set in: "face", "size" (its capitals as
    tall as the print's; "cap" is what share of the size they reach) and
    "bold" are added to each.

    The face is the page's: each line long enough votes for the face that
    covers its print best, one line alone being too short to tell. A line
    is bold where its strokes stand out from the page's lightest by most of
    the gap between its face's regular and bold. How much heavier than the
    face as cut a scan prints every line is the builder's to make up: it
    knows the face it sets, and each word's ink ("area") says how much.
    """
    votes = {face: 0 for face in FACES}
    for line in lines:
        if _letters(line["text"]) >= _FACE_MIN_LETTERS and line.get("scores"):
            votes[max(line["scores"], key=lambda f: max(line["scores"][f]))] += 1
    face = max(votes, key=lambda f: (votes[f], f == "serif"))

    def excess(line) -> float:
        size = size_in(face, line["height"], line["text"])
        regular = STROKE_EM[face][1 if line["italic"] else 0][0]
        return line["stroke"] / size - regular if size > 0 else 0.0

    weighed = sorted(excess(l) for l in lines if _letters(l["text"]) >= _WEIGHT_MIN_LETTERS and l["stroke"]
                     and size_in(face, l["height"], l["text"]))
    lightest = weighed[len(weighed) // 5] if weighed else 0.0

    def heavy(stroke: float, size: float, italic: bool) -> bool:
        stems = STROKE_EM[face][1 if italic else 0]
        return bool(stroke) and size > 0 and stroke / size - stems[0] - lightest > _BOLD_GAIN * (stems[1] - stems[0])

    sizes = [size_in(face, l["height"], l["text"]) for l in lines]
    for line, size in zip(lines, sizes):
        if not size:
            # a line of neither capitals nor ascenders ("in separate
            # sections.") is set in the size of the nearest line that has
            # in its own column
            def apart(k: int) -> Tuple[bool, float]:
                other = lines[k]["box"]
                beside = other[2] <= line["box"][0] or line["box"][2] <= other[0]
                return beside, abs(lines[k]["baseline"] - line["baseline"])
            near = min((k for k, other in enumerate(sizes) if other), key=apart, default=None)
            size = sizes[near] if near is not None else 0.0
        line.update({"face": face, "bold": heavy(line["stroke"], size, line["italic"]), "cap": CAP_EM[face],
                     "size": size})
    # Each word in its own weight, against the page's usual for its kind,
    # read off its body lines (_BODY_CHARS): lowercase; capitalized, its
    # capital a little heavier; capitals and figures - straight stems, few
    # curves - heavier still ("RAM" 0.86 to the paragraph fixture D's
    # lowercase 0.71). A word too short to weigh goes with the word
    # before it.
    def kind(text: str) -> int:
        if not any(ch.islower() for ch in text):
            return 2
        return 1 if next(ch for ch in text if ch.isalpha()).isupper() else 0

    def glyphs(text: str) -> int:
        return sum(ch.isalnum() for ch in text)

    def weighed(line) -> List[Any]:
        return [w for w in line["words"] if len(w) > 4 and w[4].get("weight")
                and glyphs(w[2]) >= _WORD_MIN_GLYPHS]

    def middle(of: List[Dict[str, Any]], k: int) -> float:
        found = sorted(w[4]["weight"] for l in of for w in weighed(l) if kind(w[2]) == k)
        return found[len(found) // 2] if len(found) >= _WEIGHT_MIN_WORDS else 0.0

    body = [l for l in lines if len(l["text"]) >= _BODY_CHARS]
    usual = {0: middle(body, 0) or middle(lines, 0)}
    usual[1] = middle(body, 1) or usual[0]
    usual[2] = middle(body, 2) or usual[0] * _CAPITALS_WEIGHT
    ratios = [[w[4]["weight"] / usual[kind(w[2])] for w in weighed(l) if usual[kind(w[2])]] for l in lines]
    weights = [sorted(r)[len(r) // 2] if r else None for r in ratios]

    # What the text around a line weighs: the middle of the lines' of its
    # column within _AROUND_LINES of it.
    def around(k: int) -> float:
        box = lines[k]["box"]
        reach = _AROUND_LINES * (box[3] - box[1])
        near = sorted(weights[j] for j, other in enumerate(lines)
                      if j != k and len(ratios[j]) >= _AROUND_WORDS
                      and other["box"][0] < box[2] and box[0] < other["box"][2]
                      and abs(other["box"][1] + other["box"][3] - box[1] - box[3]) / 2 <= reach)
        return near[len(near) // 2] if len(near) >= _AROUND_MIN else 1.0

    # A line is bold where its words weigh more than the text around it
    # and than the page's usual (_LINE_BOLD) - its strokes' width, a pixel
    # or two over a short line, called "in separate sections." bold. A
    # word of a bold line is bold but where it weighs as the text around;
    # one of a regular line, a bold run in it, where it weighs a fifth more
    # (_WORD_BOLD).
    for k, line in enumerate(lines):
        level = max(1.0, around(k))
        if weights[k] is not None:
            line["bold"] = weights[k] >= _LINE_BOLD * level
        before = None
        for word in line["words"]:
            if len(word) < 5:
                continue
            own = word[4]
            typical = usual[kind(word[2])]
            if glyphs(word[2]) >= _WORD_MIN_GLYPHS and typical and own.get("weight"):
                bold = own["weight"] >= (_LINE_BOLD if line["bold"] else _WORD_BOLD) * typical * level
            else:
                bold = before["bold"] if before else line["bold"]
            # a lean is told by stems; a word of diagonals ("every") leans
            # as it is drawn
            italic = (own["slant"] >= ITALIC_SLANT if sum(ch in _STEMS for ch in word[2]) >= 2
                      else line["italic"])
            word[4] = before = {"bold": bold, "italic": italic}
            if "glyphs" in own:
                word[4]["glyphs"] = own["glyphs"]
    # A number alone ("5", "3.2") is too few glyphs to measure: it stands on
    # the baseline of, and is set at the size of, the longest line its
    # source box shares its row with.
    def shared(a, b) -> float:
        lo, hi = max(a["source"][1], b["source"][1]), min(a["source"][3], b["source"][3])
        return (hi - lo) / max(1e-6, min(a["source"][3] - a["source"][1], b["source"][3] - b["source"][1]))

    for line in lines:
        if len(line["text"].strip()) <= _SHORT_TOKEN:
            mates = [o for o in lines if o is not line and len(o["text"].strip()) > _SHORT_TOKEN
                     and shared(o, line) >= _SAME_ROW]
            if mates:
                mate = max(mates, key=lambda o: len(o["text"]))
                line["baseline"] = mate["baseline"] + mate["skew"] * (line["box"][0] - mate["box"][0])
                line["size"] = mate["size"]
    # One kind of line - its weight and slant - is set at one size on a
    # page: a line measured off it by less than _SAME_SIZE - a row or two
    # of its capitals - is set at its kind's usual. A line a fifth larger
    # is set so: the MCS-40 manual's "THE FUNCTIONS OF A COMPUTER", 9.0pt
    # to its body's 7.4, set at 7.4 came out its body text.
    for kind in {(l["bold"], l["italic"]) for l in lines}:
        same = [l for l in lines if (l["bold"], l["italic"]) == kind]
        if len(same) < 3:
            continue
        usual = sorted(l["size"] for l in same)[len(same) // 2]
        for line in same:
            if abs(line["size"] / usual - 1.0) < _SAME_SIZE:
                line["size"] = usual


def _runs_of(np, ink) -> List[List[int]]:
    """A mask as its rows' runs of ink: [row, first column, end column]."""
    out: List[List[int]] = []
    for r, row in enumerate(ink):
        steps = np.flatnonzero(np.diff(np.concatenate(([False], row, [False])).astype(np.int8)))
        out.extend([r, int(a), int(b)] for a, b in zip(steps[::2], steps[1::2]))
    return out


_GYRE = {"serif": "texgyretermes", "sans": "texgyreheros", "mono": "texgyrecursor", "schoolbook": "texgyreschola"}


def _set_miss(np, pymupdf, mask, x0: float, y0: float, word: List[Any], line: Dict[str, Any]) -> Optional[float]:
    """How much of a word's print its text, set as the builder sets it,
    misses - and of the set text, its print: the word's face, weight, lean
    and size, on the line's baseline, as wide as the print's ink; the share
    of either's ink with no ink of the other within a pixel. mask is the
    print's ink, its top left corner at (x0, y0) pt. None where the face's
    file cannot be found."""
    variant = ("bold" if word[4].get("bold") else "") + ("italic" if word[4].get("italic") else "") or "regular"
    path = _font_file(f"{_GYRE.get(line['face'], 'texgyretermes')}-{variant}.otf")
    if not path:
        return None
    rows, cols = mask.shape
    text = word[2].strip()
    base = line["baseline"] + (line.get("skew") or 0.0) * (x0 - line["box"][0]) - y0
    doc = pymupdf.open()
    page = doc.new_page(width=line["size"] * (len(text) + 2), height=rows / _ZOOM)
    page.insert_font(fontname="F", fontfile=path)
    page.insert_text((line["size"], base), text, fontsize=line["size"], fontname="F")
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_ZOOM, _ZOOM))
    doc.close()
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    drawn = grey[:rows] < _INK_LEVEL
    if drawn.shape[0] < rows:
        drawn = np.vstack([drawn, np.zeros((rows - drawn.shape[0], drawn.shape[1]), dtype=bool)])
    printed_cols, drawn_cols = np.flatnonzero(mask.any(axis=0)), np.flatnonzero(drawn.any(axis=0))
    if not len(printed_cols) or not len(drawn_cols):
        return None
    c0, c1 = int(printed_cols[0]), int(printed_cols[-1]) + 1
    d0, d1 = int(drawn_cols[0]), int(drawn_cols[-1]) + 1
    set_ = np.zeros_like(mask)
    set_[:, c0:c1] = drawn[:, d0 + (np.arange(c1 - c0) * (d1 - d0)) // (c1 - c0)]
    near_set, near_print = _thickened(np, set_), _thickened(np, mask)
    total = int(mask.sum()) + int(set_.sum())
    return float((mask & ~near_set).sum() + (set_ & ~near_print).sum()) / total if total else None


def _fit_baseline(np, pymupdf, page, line: Dict[str, Any]) -> None:
    """Move a line's baseline to where its words, set in its face, weight,
    lean and size - each as wide as its print, on its skew - lie best over
    the print: the shift, within _FIT_REACH, whose set darkness correlates
    best with the scan's (rendered at _FIT_ZOOM, between rows by a parabola
    through the best three). Read off its rows' ink alone, a baseline is a
    row of a sixth of a point, and a line set a row off its print showed
    all along it - the paragraph fixture E's last line of three stood a
    third of a point closer to its first than it printed. Darkness, not
    ink past a threshold, and blur moves no peak. A line of fewer than
    _FIT_MIN_WORDS words keeps its own."""
    words = [w for w in line.get("words") or [] if len(w) > 4 and w[2].strip()]
    if len(words) < _FIT_MIN_WORDS or not line.get("size"):
        return
    x0, y0, x1, y1 = line["box"]
    clip = pymupdf.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1) & page.rect
    if clip.is_empty:
        return
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_FIT_ZOOM, _FIT_ZOOM), clip=clip)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    scan = np.clip(np.median(grey) - grey, 0, None)
    reach = int(round(_FIT_REACH * _FIT_ZOOM))
    doc = pymupdf.open()
    sheet = doc.new_page(width=clip.width, height=clip.height + 2 * _FIT_REACH)
    fonts: Dict[str, Any] = {}
    for w in words:
        facts = w[4]
        variant = ("bold" if facts.get("bold") else "") + ("italic" if facts.get("italic") else "") or "regular"
        if variant not in fonts:
            path = _font_file(f"{_GYRE.get(line['face'], 'texgyreheros')}-{variant}.otf")
            if not path:
                doc.close()
                return
            sheet.insert_font(fontname=f"F{len(fonts)}", fontfile=path)
            fonts[variant] = (f"F{len(fonts)}", pymupdf.Font(fontfile=path))
        name, font = fonts[variant]
        advance = font.text_length(w[2].strip(), fontsize=line["size"])
        if advance <= 0:
            continue
        at = pymupdf.Point(w[0] - clip.x0, line["baseline"] + (line.get("skew") or 0.0) * (w[0] - x0)
                           - clip.y0 + _FIT_REACH)
        sheet.insert_text(at, w[2].strip(), fontsize=line["size"], fontname=name,
                          morph=(at, pymupdf.Matrix(max(0.2, (w[1] - w[0]) / advance), 0, 0, 1, 0, 0)))
    img = sheet.get_pixmap(matrix=pymupdf.Matrix(_FIT_ZOOM, _FIT_ZOOM))
    doc.close()
    set_grey = np.frombuffer(img.samples, dtype=np.uint8).reshape(img.height, img.width, img.n)[:, :, :3].mean(axis=2)
    setd = 255.0 - set_grey
    h, w_ = scan.shape[0], min(scan.shape[1], setd.shape[1])
    a = scan[:, :w_]
    scores = []
    for k in range(-reach, reach + 1):
        # the set text k rows lower over the print: its rows from reach - k
        s = setd[reach - k:reach - k + h, :w_]
        if s.shape != a.shape:
            scores.append(-1.0)
            continue
        scores.append(float((a * s).sum() / max(1e-9, np.sqrt((a * a).sum() * (s * s).sum()))))
    best = int(np.argmax(scores))
    if scores[best] < _FIT_MIN_LIKENESS or best in (0, len(scores) - 1):
        return
    lo, mid, hi = scores[best - 1], scores[best], scores[best + 1]
    curve = lo - 2.0 * mid + hi
    between = 0.5 * (lo - hi) / curve if curve < 0 else 0.0
    line["baseline"] += (best - reach + between) / _FIT_ZOOM


def _mark_misread(np, pymupdf, lines: List[Dict[str, Any]]) -> None:
    """Keep the ink of each word of a page's lines its text does not draw:
    OCR read a subscript as letters of the line ("tRCD" for t-sub-RCD),
    an arrow as a dash. A word whose text, set as the builder sets it,
    misses more than _MISREAD of the ink (_set_miss), or with letters set
    lower than its text has (_lowered), is drawn from its print - its ink
    as runs of pixels ("ink": "box" page-normalised, "shape", "runs") -
    its text kept for what reads it."""
    for line in lines:
        judged = []
        for word, (mask, x0, y0) in zip(line["words"], line.get("marks") or []):
            if len(word) < 5 or not word[2].strip() or not mask.any():
                continue
            miss = _set_miss(np, pymupdf, mask, x0, y0, word, line)
            if miss is None:
                continue
            word[4]["miss"] = miss
            sign = not any(ch.isalnum() for ch in word[2])
            misread = miss > (_MISREAD_SIGN if sign else _MISREAD) or _lowered(np, mask, x0, y0, word[2], line)
            judged.append((word, mask, x0, y0, misread))
        # a line OCR misread half of is misread whole: a formula's line,
        # its arrows read as dashes, its subscripts as letters
        whole = len(judged) >= 2 and 2 * sum(m for *_, m in judged) >= len(judged)
        for word, mask, x0, y0, misread in judged:
            if misread or whole:
                rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
                ink = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
                pw, ph = line["pw"], line["ph"]
                box = [x0 + cols[0] / _ZOOM, y0 + rows[0] / _ZOOM, x0 + (cols[-1] + 1) / _ZOOM, y0 + (rows[-1] + 1) / _ZOOM]
                word[4]["ink"] = {"box": [box[0] / pw, box[1] / ph, box[2] / pw, box[3] / ph],
                                  "shape": list(ink.shape), "runs": _runs_of(np, ink)}


def _lowered(np, mask, x0: float, y0: float, text: str, line: Dict[str, Any]) -> bool:
    """Whether a word prints letters set lower than its text has them - a
    subscript, "RCD" of t-sub-RCD that OCR read as letters of the line:
    more runs of its ink (mask, its top left corner at x0, y0 pt) reach
    under the line's baseline by _LOWERED of its capitals' height than
    its text has letters that do ("gjpqy", brackets). A subscript's
    capitals stand as tall as the line's lowercase, a descender's "p"
    alike - only its text tells them apart."""
    deep = 0
    for a, b in _glyph_spans(np, mask):
        rows = np.flatnonzero(mask[:, a:b].any(axis=1))
        x = x0 + (a + b) / 2.0 / _ZOOM
        base = line["baseline"] + (line.get("skew") or 0.0) * (x - line["box"][0])
        deep += y0 + (rows[-1] + 1) / _ZOOM - base > _LOWERED * line["height"]
    return deep > sum(ch in _DESCENDING for ch in text)


def _normalised(facts: Dict[str, Any], pw: float) -> Dict[str, Any]:
    """A word's facts with its letters' places (pt) as page shares."""
    if "glyphs" not in facts:
        return facts
    return {**facts, "glyphs": [[a / pw, b / pw] for a, b in facts["glyphs"]]}


def read_printed_lines(np, pymupdf, source, items: List[Any]) -> List[Any]:
    """How a set of lines was printed, as a page rebuilt where it was
    printed needs it: items are (owner, part, page index, page-normalised
    box, text) for each line, source the opened PDF. Each line is measured
    (measure_line, with the page's words inside its box) - at its column's
    skew (_settled_skews) - each page's lines settled together
    (settle_page), and returned as (owner, line) - line a
    dict of the line's print: "part", "text", "page", its ink "box" and
    "baseline" (page-normalised), "skew", its "words" ([x0, x1, text,
    area, {"bold", "italic", "glyphs" - the runs its ink falls apart into
    across, [x0, x1] each, "ink" - a misread word's print}], x
    page-normalised), "area",
    "cap", "size", "face", "bold",
    "italic", "rgb", "underline" ([y page-normalised, thickness pt]),
    "overlines" ([x0, x1, y page-normalised, thickness pt] each), "page_pt"
    - its page's width and height."""
    measured: List[Any] = []
    words: Dict[int, List[Any]] = {}
    for owner, part, page_index, box, text in items:
        if page_index is None or page_index >= source.page_count:
            continue
        page = source[page_index]
        pw, ph = page.rect.width, page.rect.height
        rect = pymupdf.Rect(box[0] * pw, box[1] * ph, box[2] * pw, box[3] * ph)
        if page_index not in words:
            words[page_index] = page.get_text("words")
        own = [w for w in words[page_index]
               if rect.x0 <= (w[0] + w[2]) / 2 <= rect.x1 and rect.y0 <= (w[1] + w[3]) / 2 <= rect.y1]
        m = measure_line(np, pymupdf, page, rect, text, own)
        if m is not None:
            m.update({"part": part, "text": text, "page": page_index, "pw": pw, "ph": ph,
                      "rect": rect, "own": own})
            measured.append((owner, m))
    for page_index in sorted({m["page"] for _, m in measured}):
        # each line measured anew at its column's skew (_settled_skews) -
        # its baseline and capitals read off it stood straight by it
        here = [k for k, (_, m) in enumerate(measured) if m["page"] == page_index]
        for k, skew in zip(here, _settled_skews([measured[k][1] for k in here])):
            owner, m = measured[k]
            if skew != m["skew"]:
                again = measure_line(np, pymupdf, source[page_index], m["rect"], m["text"], m["own"], skew)
                if again is not None:
                    again.update({key: m[key] for key in ("part", "text", "page", "pw", "ph")})
                    measured[k] = (owner, again)
        settle_page([m for _, m in measured if m["page"] == page_index])
        for m in (m for _, m in measured if m["page"] == page_index):
            _fit_baseline(np, pymupdf, source[page_index], m)
        _mark_misread(np, pymupdf, [m for _, m in measured if m["page"] == page_index])
    out = []
    for owner, m in measured:
        pw, ph = m["pw"], m["ph"]
        x0, y0, x1, y1 = m["box"]
        out.append((owner, {
            "part": m["part"], "text": m["text"], "page": m["page"],
            "box": [x0 / pw, y0 / ph, x1 / pw, y1 / ph], "baseline": m["baseline"] / ph,
            "skew": m["skew"],
            "words": [[w[0] / pw, w[1] / pw] + list(w[2:4]) + [_normalised(w[4], pw)] if len(w) > 4
                      else [w[0] / pw, w[1] / pw] + list(w[2:]) for w in m["words"]],
            "area": m["area"], "cap": m["cap"],
            "size": m["size"], "face": m["face"], "bold": m["bold"], "italic": m["italic"],
            "rgb": m["rgb"],
            "underline": [m["underline"][0] / ph, m["underline"][1]] if m["underline"] else None,
            "overlines": [[a / pw, b / pw, y / ph, t] for a, b, y, t in m["overlines"]],
            "page_pt": [pw, ph],
        }))
    return out
