import fitz


def save_page_images(doc, page, page_num: int,
                     blocks: list[dict], img_dir: str) -> int:
    import os

    saved = 0
    image_blocks = [b for b in blocks if b["block_type"] == "image"]

    for j, img_info in enumerate(page.get_images(full=True)):
        xref = img_info[0]
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.n > 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.width < 50 or pix.height < 50:
                continue

            fname = f"page_{page_num}_img_{j}.png"
            pix.save(os.path.join(img_dir, fname))
            saved += 1

            rects = page.get_image_rects(xref)
            if rects:
                img_rect = rects[0]
                best_block = None
                best_overlap = 0
                for b in image_blocks:
                    if b.get("image_file"):
                        continue
                    block_rect = fitz.Rect(b["x0"], b["y0"], b["x1"], b["y1"])
                    overlap = abs(block_rect & img_rect)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_block = b
                if best_block:
                    best_block["image_file"] = fname
            else:
                for b in image_blocks:
                    if not b.get("image_file"):
                        b["image_file"] = fname
                        break
        except Exception:
            pass
    return saved
