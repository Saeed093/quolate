"""Generate synthetic ingestion fixtures in code (no binary assets checked in)."""
from __future__ import annotations

import io
import zipfile


def text_layer_pdf(lines: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    out = doc.tobytes()
    doc.close()
    return out


def png_price_table(lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 60 + 30 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black")
        y += 30
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def image_only_pdf(lines: list[str]) -> bytes:
    """A PDF whose only content is a rasterized image (no text layer)."""
    import fitz
    from PIL import Image

    img_bytes = png_price_table(lines)
    im = Image.open(io.BytesIO(img_bytes))
    w, h = im.size
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.insert_image(fitz.Rect(0, 0, w, h), stream=img_bytes)
    out = doc.tobytes()
    doc.close()
    return out


def xlsx_price_list(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Prices"
    for row in rows:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def whatsapp_zip(chat_text: str, images: list[bytes] | None = None) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_chat.txt", chat_text)
        for i, img in enumerate(images or []):
            zf.writestr(f"IMG-2024010{i}.png", img)
    return bio.getvalue()
