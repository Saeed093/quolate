"""OCR seam. `run_ocr` is monkeypatched in tests so PaddleOCR isn't required."""
from __future__ import annotations

from app.ocr.paddle import OcrLine, OcrPage, run_ocr

__all__ = ["OcrLine", "OcrPage", "run_ocr"]
