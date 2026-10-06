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
import subprocess
from typing import Any, Dict, List, Optional

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
_ASCENDERS = set("bdfhklt")
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
_SAME_SIZE = 0.3          # within this of its kind's usual size, a line is set at it
_SHORT_TOKEN = 3          # characters in a token too short to measure its size by
_SAME_ROW = 0.5           # of the lower box's height two source boxes share on one row
_BOLD_GAIN = 0.6          # of the gap from regular to bold, over the page's lightest
# Of the page's usual weight, a word's in a bold run: on the paragraph
# fixture D regular words weigh 0.61-0.80pt (usual 0.71), bold ones 0.90-1.07.
_WORD_BOLD = 1.2
_STEMS = set("bdhiklmnpqrtuBDEFHIKLMNPRTU")  # letters with an upright stem to lean

ITALIC_SLANT = 0.12       # tan of the lean; an italic leans 0.2 or so
_INK_LEVEL = 160          # 0-255 grey below which a pixel is ink, for face likeness
_GLYPH_CONTRAST = 120     # summed RGB difference from what a glyph is printed on
_RULE_SPAN = 0.9          # a row this full of ink is a rule crossing the line
_UNDERLINE_SPAN = 0.8     # a rule under the line covering this much of it underlines it
_BASELINE_DENSITY = 0.3   # a row this dense against the line's densest is above the baseline
_BASELINE_FALL = 0.6      # the row under the baseline holds less than this of its ink
# of a line's box height: the widest gap between two letters of a word -
# the paragraph fixture D's "c" and "h" of "each" stand 0.83pt apart at 8pt
_LETTER_GAP = 0.15
_HEAD_DENSITY = 0.08      # a row this dense against the line's densest is its capitals', not a stray descender
_COLOUR_SPREAD = 80       # channels this far apart: printed in a colour, not black
_MISREAD = 0.5            # of a word's and its set text's ink, the most one misses of the other
_OVERLINE_REACH = 0.35    # of a line's ink height: how far over its top an overline stands
_OVERLINE_DIP = 0.1       # of it: how far under its top - an overline is its topmost ink, a hyphen is not
_OVERLINE_MIN = 0.4       # of a line's ink height: the shortest overline, over one capital
_OVERLINE_THICK = 0.15    # of a line's ink height: the thickest
_OVERLINE_CLEAR = 0.2     # of its length, the most ink a row over an overline holds (a descender through it)
_ZOOM = 6.0


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
    """A line's baseline row: down from its densest row, the first its ink
    falls away under by _BASELINE_FALL - from the body of the line to its
    descenders. Neither the last row of some density nor the steepest fall:
    a typewriter's heavy "pp" fill the rows under "Appendix"'s baseline as
    densely, and their ends fall away as steeply."""
    # down from its densest row, the first where the ink falls away sharply
    # for good - nothing under it as dense again: figures narrow halfway
    # down ("12, 13") and fill out again at their feet
    for r in range(int(np.argmax(band)), len(band)):
        rest = band[r + 1:].max() if r + 1 < len(band) else 0.0
        if band[r] >= _BASELINE_DENSITY * band.max() and rest < _BASELINE_FALL * band[r]:
            return r
    below = np.append(band[1:], 0)
    rows = np.flatnonzero(band >= _BASELINE_DENSITY * band.max())
    return int(rows[np.argmax(band[rows] - below[rows])])


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


def _skew(np, region) -> float:
    """How far a line's baseline falls over its width (dy/dx), from the
    baseline of each of its thirds."""
    h, w = region.shape
    feet = []
    for k in range(3):
        a, b = k * w // 3, (k + 1) * w // 3
        if b - a < 2:
            continue
        foot, _ = _foot_and_head(np, region[:, a:b].mean(axis=1))
        if foot is not None:
            feet.append(((a + b) / 2.0, float(foot)))
    if len(feet) < 2:
        return 0.0
    return float(np.polyfit([f[0] for f in feet], [f[1] for f in feet], 1)[0])


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


def _overlines(np, glyphs, top: int, bottom: int, left: int, right: int) -> List[Any]:
    """Rules drawn over a line's letters - a signal active low, "RAS" with
    a bar over it - as (first row, last row, first column, end column): a
    few thin rows inked along in one run, all but clear over it, standing
    over the tops of the line's letters - those read beside the bars, a
    scan's blur joining a bar to the letters under it. A capital's own bar
    ("T", "E") stands at their tops, its stem under it."""
    h = bottom - top + 1
    rows = glyphs.shape[0]
    thick = max(1, int(round(_OVERLINE_THICK * h)))
    min_len = max(3, int(_OVERLINE_MIN * h))
    bars: List[Any] = []
    taken = np.zeros(glyphs.shape, dtype=bool)
    for r in range(max(0, top - int(_OVERLINE_REACH * h)), min(rows, top + int(_OVERLINE_DIP * h) + 1)):
        line = np.concatenate(([False], glyphs[r, left:right], [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(line))
        for a, b in zip(edges[::2] + left, edges[1::2] + left):
            if b - a < min_len or taken[r, a:b].any():
                continue
            end = r
            while end + 1 < rows and glyphs[end + 1, a:b].mean() >= 0.8:
                end += 1
            # over it, a row all but clear along it: the bottom of the line
            # above's letters has their sides over it
            above = range(max(0, r - 1 - thick), r)
            if end + 1 - r <= thick and any(glyphs[q, a:b].mean() <= _OVERLINE_CLEAR for q in above):
                bars.append((r, end, int(a), int(b)))
                # its fainter rows under it are the same bar
                taken[r:end + 2 + thick, a:b] = True
    if not bars:
        return []
    # the tops of the line's letters, read where no bar stands
    rest = glyphs[:, left:right].copy()
    for _, _, a, b in bars:
        rest[:, a - left:b - left] = False
    density = rest[top:bottom + 1].sum(axis=1)
    heads = np.flatnonzero(density >= _HEAD_DENSITY * max(1, density.max()))
    head = top + int(heads[0]) if len(heads) else top
    return [bar for bar in bars if bar[1] <= head]


def _weight_of(np, ink) -> float:
    """How thick ink's strokes are, in pixels: twice its area over its
    outline. Unlike a median run across the strokes it does not step by
    whole pixels - a scan's strokes are three of them wide."""
    padded = np.pad(ink, 1)
    outline = int((padded[1:, :] != padded[:-1, :]).sum() + (padded[:, 1:] != padded[:, :-1]).sum())
    return 2.0 * float(ink.sum()) / outline if outline else 0.0


def _word_inks(np, region, body, words, x_of, gap: int) -> List[List[Any]]:
    """Where each word of a line prints: its ink's left and right column in
    region (x_of turns a page point into a region column). OCR boxes a word
    by its own guess - short of a glyph, or over a letter of the next - so
    the words are read off the ink: its lowercase body (body: those rows'
    ink by column, which no "f" hook or "y" tail overhangs a space through)
    falls into runs of letters, apart where a gap is wider than gap columns,
    and each run goes to the word whose box holds its middle. A run two
    boxes hold is cut at its widest gap between them. A word's edges are its
    runs' ink in all its rows, short of the middle of the space to either
    neighbour; a word no run goes to is left out."""
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
    for lo, hi in runs:
        held = sorted({k for k, (a, b, _) in enumerate(boxes) if a < hi and lo < b and (a + b) / 2 >= lo - gap and (a + b) / 2 < hi + gap})
        if len(held) > 1:
            # one run, two words' boxes: cut at its widest gap near each seam
            cuts = []
            for k0, k1 in zip(held, held[1:]):
                seam = (boxes[k0][1] + boxes[k1][0]) // 2
                lo_s, hi_s = max(lo + 1, seam - 2 * gap), min(hi - 1, seam + 2 * gap)
                empty = [c for c in range(lo_s, hi_s) if not body[c]]
                cuts.append(min(empty, key=lambda c: abs(c - seam)) if empty else seam)
            edges = [lo] + cuts + [hi]
            for k, a, b in zip(held, edges, edges[1:]):
                owned.setdefault(k, []).extend([a, b])
            continue
        k = holder((lo + hi) / 2)
        if k is not None:
            owned.setdefault(k, []).extend([lo, hi])
    spans = [[min(owned[k]), max(owned[k]), boxes[k][2]] for k in sorted(owned)]
    out = []
    for k, (lo, hi, text) in enumerate(spans):
        left = (spans[k - 1][1] + lo) // 2 if k > 0 else 0
        right = (hi + spans[k + 1][0]) // 2 if k + 1 < len(spans) else w
        full = np.flatnonzero(inked[left:right])
        if len(full):
            lo, hi = min(lo, left + int(full[0])), max(hi, left + int(full[-1]) + 1)
        out.append([lo, hi, text])
    return out


def measure_line(np, pymupdf, page, rect, text: str, words: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:

    """The print of one line, boxed (in points) at rect by its source.

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
    # skew is read from the baseline of each third of the line, the line
    # is stood straight by it, and its baseline and capitals' top are read
    # off the straightened ink - askew, they smear over the fall.
    region = glyphs[top:bottom + 1, left:right]
    skew = _skew(np, region)
    upright = _straightened(np, region, skew)
    foot, head = _foot_and_head(np, upright.mean(axis=1))
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
    bars = _overlines(np, glyphs, top, bottom, left, right)
    for r0, r1, a, b in bars:
        dark[r0:r1 + 1, a:b] = False
    overlines = [[pt_x(a), pt_x(b), pt_y((r0 + r1 + 1) / 2.0), (r1 + 1 - r0) / _ZOOM] for r0, r1, a, b in bars]

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
    if words:
        # Each word's own weight and lean, beside its line's: a bold or
        # italic word in a regular line ("refreshed", "algorithm"); and its
        # ink itself, for a word its text does not draw (read_printed_lines).
        # the lowercase body: from its middle to the baseline, straightened
        body = upright[head + (foot - head) // 2:foot + 1].any(axis=0)
        for a, b, t in _word_inks(np, region, body, words, lambda x: (x - clip.x0) * _ZOOM - left,
                                  max(1, int(rect.height * _ZOOM * _LETTER_GAP))):
            own = dark[top:bottom + 1, left + a:left + b]
            placed.append([pt_x(left + a), pt_x(left + b), t, float(own.sum()) / _ZOOM ** 2,
                           {"weight": _weight_of(np, own) / _ZOOM,
                            "slant": slant(np, region[:, a:b]) if region[:, a:b].any() else 0.0}])
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
    ascenders - stand height tall in face."""
    tall = any(ch in _ASCENDERS for ch in text)
    capitals = any(ch.isupper() or ch.isdigit() for ch in text)
    return height / (ASCENDER_EM[face] if tall and not capitals else CAP_EM[face])


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def settle_page(lines: List[Dict[str, Any]]) -> None:
    """Decide, for the measured lines of one page (measure_line, each with
    its "text"), the type each is set in: "face", "size" (its capitals as
    tall as the print's; "cap" is what share of the size they reach) and
    "bold" are added to each, and a short line's "skew" is its neighbours'.

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

    # A short line's skew is its few glyphs' own: it takes the skew of the
    # nearest long line, scanned with it.
    long_lines = [l for l in lines if l["box"][2] - l["box"][0] >= _SKEW_MIN_PT]
    for line in lines:
        if line["box"][2] - line["box"][0] < _SKEW_MIN_PT:
            near = min(long_lines, key=lambda l: abs(l["baseline"] - line["baseline"]), default=None)
            line["skew"] = near["skew"] if near is not None else 0.0

    weighed = sorted(excess(l) for l in lines if _letters(l["text"]) >= _WEIGHT_MIN_LETTERS and l["stroke"])
    lightest = weighed[len(weighed) // 5] if weighed else 0.0

    def heavy(stroke: float, size: float, italic: bool) -> bool:
        stems = STROKE_EM[face][1 if italic else 0]
        return bool(stroke) and size > 0 and stroke / size - stems[0] - lightest > _BOLD_GAIN * (stems[1] - stems[0])

    for line in lines:
        size = size_in(face, line["height"], line["text"])
        line.update({"face": face, "bold": heavy(line["stroke"], size, line["italic"]), "cap": CAP_EM[face],
                     "size": size})
    # Each word in its own weight, against the page's usual: a word in a
    # bold run weighs a fifth again and more (_WORD_BOLD). A letter alone
    # is too little to weigh; it goes with the word before it.
    weights = sorted(w[4]["weight"] for l in lines for w in l["words"]
                     if len(w) > 4 and _letters(w[2]) >= 3 and w[4]["weight"])
    usual = weights[len(weights) // 2] if weights else 0.0
    for line in lines:
        before = None
        for word in line["words"]:
            if len(word) < 5:
                continue
            own = word[4]
            if _letters(word[2]) >= 2 and usual:
                bold = own["weight"] >= _WORD_BOLD * usual
            else:
                bold = before["bold"] if before else line["bold"]
            # a lean is told by stems; a word of diagonals ("every") leans
            # as it is drawn
            italic = (own["slant"] >= ITALIC_SLANT if sum(ch in _STEMS for ch in word[2]) >= 2
                      else line["italic"])
            word[4] = before = {"bold": bold, "italic": italic}
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
    # page: a line measured off it by less than _SAME_SIZE is set at its
    # kind's usual. On a page scanned askew a descender of the line above
    # touches the next line's capitals, and read so "Introduction, Basic
    # Programming Choices" came to 17.4pt among its neighbours' 13.8.
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


def _mark_misread(np, pymupdf, lines: List[Dict[str, Any]]) -> None:
    """Keep the ink of each word of a page's lines its text does not draw:
    OCR read a subscript as letters of the line ("tRCD" for t-sub-RCD),
    an arrow as a dash. A word whose text, set as the builder sets it,
    misses more than _MISREAD of the ink (_set_miss) is drawn from its
    print - its ink as runs of pixels ("ink": "box" page-normalised,
    "shape", "runs") - its text kept for what reads it."""
    for line in lines:
        for word, (mask, x0, y0) in zip(line["words"], line.get("marks") or []):
            if len(word) < 5 or not word[2].strip() or not mask.any():
                continue
            miss = _set_miss(np, pymupdf, mask, x0, y0, word, line)
            if miss is None:
                continue
            word[4]["miss"] = miss
            if miss > _MISREAD:
                rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
                ink = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
                pw, ph = line["pw"], line["ph"]
                box = [x0 + cols[0] / _ZOOM, y0 + rows[0] / _ZOOM, x0 + (cols[-1] + 1) / _ZOOM, y0 + (rows[-1] + 1) / _ZOOM]
                word[4]["ink"] = {"box": [box[0] / pw, box[1] / ph, box[2] / pw, box[3] / ph],
                                  "shape": list(ink.shape), "runs": _runs_of(np, ink)}


def read_printed_lines(np, pymupdf, source, items: List[Any]) -> List[Any]:
    """How a set of lines was printed, as a page rebuilt where it was
    printed needs it: items are (owner, part, page index, page-normalised
    box, text) for each line, source the opened PDF. Each line is measured
    (measure_line, with the page's words inside its box), each page's lines
    settled together (settle_page), and returned as (owner, line) - line a
    dict of the line's print: "part", "text", "page", its ink "box" and
    "baseline" (page-normalised), "skew", its "words" ([x0, x1, text,
    area, {"bold", "italic"}], x page-normalised), "area", "cap", "size", "face", "bold",
    "italic", "rgb", "underline" ([y page-normalised, thickness pt]),
    "overlines" ([x0, x1, y page-normalised, thickness pt] each)."""
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
            m.update({"part": part, "text": text, "page": page_index, "pw": pw, "ph": ph})
            measured.append((owner, m))
    for page_index in sorted({m["page"] for _, m in measured}):
        settle_page([m for _, m in measured if m["page"] == page_index])
        _mark_misread(np, pymupdf, [m for _, m in measured if m["page"] == page_index])
    out = []
    for owner, m in measured:
        pw, ph = m["pw"], m["ph"]
        x0, y0, x1, y1 = m["box"]
        out.append((owner, {
            "part": m["part"], "text": m["text"], "page": m["page"],
            "box": [x0 / pw, y0 / ph, x1 / pw, y1 / ph], "baseline": m["baseline"] / ph,
            "skew": m["skew"],
            "words": [[w[0] / pw, w[1] / pw] + list(w[2:]) for w in m["words"]],
            "area": m["area"], "cap": m["cap"],
            "size": m["size"], "face": m["face"], "bold": m["bold"], "italic": m["italic"],
            "rgb": m["rgb"],
            "underline": [m["underline"][0] / ph, m["underline"][1]] if m["underline"] else None,
            "overlines": [[a / pw, b / pw, y / ph, t] for a, b, y, t in m["overlines"]],
        }))
    return out
