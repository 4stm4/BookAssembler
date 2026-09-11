"""toc: what marks a table of contents — headings, entry shapes, thresholds.

These are the attributes by which the entity is recognised. The methods that
apply them live in rules.py (text) and layout.py (geometry); reading KRM
nodes lives in the analyzer.

Measured on ten books of different make (docs/deploy/testing-the-pipeline.md):
TeX/texinfo/asciidoc output, Word-era manuals, 1970s scans with and without
OCR errors, one and two columns, Russian and English.
"""

import re

# The heading that opens a contents page, matched against a whole short line.
_TOC_HEADING_RE = re.compile(
    r"^\s*(?:table\s+of\s+contents|contents|оглавление|содержание|зміст"
    r"|inhaltsverzeichnis|inhalt|table\s+des\s+mati[eè]res|sommaire)\s*$",
    re.IGNORECASE,
)

# OCR mangles the heading of a scanned contents page ("TABlE or conTEnTS" on
# the Signetics 8080 manual). Compared letters-only, lowercased, within a
# small edit distance — only for the long forms, where a two-letter slip
# cannot turn some other word into a match ("consents" is one edit from
# "contents", so the bare word is matched exactly or not at all).
_FUZZY_HEADINGS = ("tableofcontents", "оглавление", "содержание")
FUZZY_HEADING_MAX_EDITS = 2

# A heading after which the contents list is over: the next front-matter
# list (Zilog Z80 manual: "List of Figures" follows the contents pages and is
# laid out exactly like them).
_STOP_HEADING_RE = re.compile(
    r"^\s*(?:list\s+of\s+(?:figures|tables|illustrations)|figures|tables"
    r"|illustrations|список\s+(?:иллюстраций|рисунков|таблиц)|перечень\s+\w+)\s*$",
    re.IGNORECASE,
)

# Characters a leader is drawn with. U+FFFD is the glyph an OCR engine emits
# for a leader it could not read (Zaks, "Programming the Z80").
LEADER_CHARS = ".·…�_"
_LEADER_CLASS = "[" + re.escape(LEADER_CHARS) + "]"

# A printed page reference: arabic, lowercase roman (front matter), or the
# chapter-page form of 1970s manuals ("2-15", "4-7").
_PAGE = r"(?:\d{1,4}(?:\s?[-–]\s?\d{1,4})?|[ivxlcdm]{1,8})"
_PAGE_RE = re.compile(r"^" + _PAGE + r"$")

# A page reference at the end of a line, after a leader: two or more dots
# ("Registers . . . 45", "Revision History. . . .iii") or any other leader
# glyph ("ORGANIZATION �46"). A bare space is not enough — "Page i" in a
# footer would read as an entry — and neither is one dot: "Migrating to
# 2016.11" is a version, not page 11.
_TRAILING_PAGE_RE = re.compile(
    r"^(?P<body>.*?(?:(?:\.\s*){2,}|[·…�_]\s*))(?P<page>" + _PAGE + r")\s*$"
)

# A page reference after a plain space — a justified column whose title
# fills the line to the edge itself (MetaPost: "Уравнения и координатные пары
# 15"). Trusted only at the column's right edge, and only after a word.
_SPACED_PAGE_RE = re.compile(
    r"^(?P<body>.*[^\W\d_].*?)\s+(?P<page>" + _PAGE + r")\s*$"
)

# A line that ends in a leader run: two or more dots, or another leader glyph.
_ENDS_WITH_LEADER_RE = re.compile(r"(?:(?:\.\s*){2,}|[·…�_]\s*)$")

# A section number standing on its own as the first line of a row
# ("1.2.1", "IV.", "A.", "HI." as OCR read "III."). Four-digit part numbers
# ("4101", "3216/") are titles in the manuals that use them, not numbers.
_NUMBER_TOKEN_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,3})*\.?|[IVXLCH]{1,5}\.|[IVXL]{1,4}|[A-ZА-Я]\.)$"
)

# The same number leading a line's text ("26.1 Caveat with…", "27.10Migration").
_LEADING_NUMBER_RE = re.compile(
    r"^(?P<num>(?:(?:Chapter|Appendix|Part|Section|Глава|Часть|Раздел|Приложение)\s+)?"
    r"(?:\d{1,2}(?:\.\d{1,3})+|\d{1,2}\.?|[IVXL]{1,4}\.|[A-ZА-Я]\.))"
    r"(?:\s+|(?=[A-ZА-ЯЁ]))(?P<rest>\S.*)$"
)

# A page's own folio or footer, not an entry: "Page i", "- 3 -", "Стр. 5".
_FOLIO_RE = re.compile(
    r"^\s*(?:(?:page|стр\.?|страница|seite)\s+\S{1,6}|[-–]\s*\d{1,4}\s*[-–]|"
    + _PAGE + r")\s*$",
    re.IGNORECASE,
)

# A contents list starts within the first pages regardless of the book's
# length. Stray "Contents" cells in tables deep in a manual (Zilog Z80: pages
# 33, 42, 295, 297) must not open one.
TOC_HEADING_MAX_PAGE = 20

# Running heads and folios sit in the page's margin bands. On a contents
# page a line there is page furniture even when it ends in a number at the
# right edge ("The Buildroot user manual  ii", "1 ВВЕДЕНИЕ  2" — both at
# y=0.045). The highest real entry measured starts at y=0.082 (Zaks).
MARGIN_TOP = 0.065
MARGIN_BOTTOM = 0.93

# Geometry, in page-normalised units unless stated otherwise.
RIGHT_EDGE_TOL = 0.03      # a page reference sits this close to the column's right edge
COLUMN_GAP = 0.05          # right edges further apart than this are different columns
MIN_COLUMN_REFS = 2        # page references needed to establish a column edge
ROW_OVERLAP = 0.5          # share of the smaller line height two lines must share to be one row
PAGE_ATTACH = 0.75         # a page reference joins the nearest row within this many row heights
CONT_TOL_CHARS = 2.5       # a wrapped line starts within this many char widths of its tab stop
CONT_MAX_GAP = 0.9         # …and no further below than this many line heights
LEVEL_X_TOL = 0.012        # entry starts closer than this share an indentation level

# A following page continues the contents when it carries this many entries
# that point to a page, and the entries with the annotation under them
# account for this share of its rows. Counting entries alone does not work:
# a Zaks contents page has three description lines per entry (5 entries,
# 26 rows) — all of them contents.
MIN_ENTRIES_PER_PAGE = 2
MIN_ACCOUNTED_SHARE = 0.6
# A contents page found without a heading must be unambiguous.
HEADINGLESS_MIN_ENTRIES = 6
HEADINGLESS_MIN_SHARE = 0.5

# Below the last entry, a row this much larger than the entries is the first
# heading of the book proper (TeX Live guide: the contents end mid-page and
# "1 Введение" follows).
HEADING_SIZE_RATIO = 1.15
# A row this long is prose, not a contents line.
PROSE_MIN_CHARS = 100
PROSE_MIN_WORDS = 14
