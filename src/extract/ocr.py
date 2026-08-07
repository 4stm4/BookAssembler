def ocr_page(page) -> str:
    try:
        tp = page.get_textpage_ocr(language="eng", dpi=300)
        text = page.get_text("text", textpage=tp).strip()
        return text if len(text) > 20 else ""
    except Exception:
        return ""
