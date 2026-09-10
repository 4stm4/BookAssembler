"""ocr: Prompt text sent to agents."""

_PROMPT = (
    "This is a scanned page with no text layer. Transcribe every line of "
    "readable text in reading order. Output one JSON object per line, nothing "
    "else:\n"
    '{"text": "...", "bbox": [x0, y0, x1, y1], "font": "serif|sans|mono", '
    '"bold": true|false}\n'
    "bbox is that line's box within the image as integers 0-1000, measured "
    "from the top-left corner. No commentary, no code fences. If the page has "
    "no readable text, output nothing."
)
