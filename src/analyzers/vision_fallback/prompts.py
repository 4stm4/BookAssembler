"""vision_fallback: Prompt text sent to agents."""

CLASSIFY_PROMPT = (
    "Look at this cropped region from a scanned document page. "
    "What type of content is shown? Answer with exactly ONE word from this list: "
    "paragraph, table, formula, figure, code, caption, heading, list, footnote, "
    "bibliography, algorithm, index, toc, blank. "
    "Then on a new line, give a confidence score 0.0-1.0."
)

FORMULA_PROMPT = (
    "This image contains a mathematical formula from a technical document. "
    "Extract the formula and write it as valid LaTeX code. "
    "Output ONLY the LaTeX expression, nothing else. "
    "Do not wrap in $ or \\begin{equation}."
)
