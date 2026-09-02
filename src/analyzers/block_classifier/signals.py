"""block_classifier: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

# Leading chapter number: "1", "1.2", "1.2.3", "A.", "IV.", "Глава 5", "Chapter 7"
_LEADING_NUM_RE = re.compile(
    r"""^\s*
    (?:
        (?P<hier>\d+(?:\.\d+){0,3}\.?)           # 1  |  1.  |  1.2  |  1.2.3
      | (?P<letter>[A-ZА-ЯЁa-zа-яё])[.)]         # A.  a.  А)
      | (?P<roman>[IVXLCDM]+)[.)]                # IV.  X)
      | (?P<word>(?:Глава|Chapter|Часть|Part|Раздел|Section|Appendix|Приложение))\s+
        (?P<word_num>[\d\wА-Яа-я]+)
    )
    \s+
    """,
    re.VERBOSE,
)

_ENDS_WITH_PAGE_NUM = re.compile(r"\s(\d{1,4}|[ivxlcdm]+|[IVXLCDM]+)\s*$")

MIN_TOC_RUN = 4

MAX_TOC_TEXT_LEN = 120
