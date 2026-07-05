"""Rasterize PDF pages to PNG bytes via PyMuPDF."""
from __future__ import annotations

DEFAULT_DPI = 200


def pdf_page_to_png(pdf_bytes: bytes, page_index: int, dpi: int = DEFAULT_DPI) -> bytes:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_index]
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def pdf_page_count(pdf_bytes: bytes) -> int:
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()
