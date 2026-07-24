"""PaddleOCR wrapper: lazy-loaded, English + Chinese passes, keep bboxes.

Picks the pass with higher mean confidence per image. Real PaddleOCR is only
imported on first use (heavy); tests monkeypatch `run_ocr`.
"""
from __future__ import annotations

import io
import queue as _queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.config import settings

# Per-language object pool of PaddleOCR instances. A single PaddleOCR predictor
# is NOT safe to call concurrently from multiple threads, so parallel page OCR
# borrows one instance per thread and returns it when done. The pool grows only
# to the peak concurrency and keeps instances warm across documents.
_POOLS: dict[str, _queue.Queue] = {}
_POOL_LOCK = threading.Lock()


@dataclass
class OcrLine:
    text: str
    bbox: list[float]  # [x0, y0, x1, y1]
    confidence: float


@dataclass
class OcrPage:
    lines: list[OcrLine] = field(default_factory=list)
    mean_confidence: float = 0.0
    lang: str = ""

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _build_model(lang: str):
    from paddleocr import PaddleOCR  # heavy import, lazy

    return PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)


def _pool_for(lang: str) -> _queue.Queue:
    with _POOL_LOCK:
        pool = _POOLS.get(lang)
        if pool is None:
            pool = _queue.Queue()
            _POOLS[lang] = pool
        return pool


@contextmanager
def _borrow_model(lang: str):
    """Check out a per-language model instance, returning it to the pool after.

    Grows the pool by one when every warm instance is in use, so the number of
    live models settles at the peak concurrency for that language.
    """
    pool = _pool_for(lang)
    try:
        model = pool.get_nowait()
    except _queue.Empty:
        model = _build_model(lang)
    try:
        yield model
    finally:
        pool.put(model)


def _to_numpy(image_bytes: bytes):
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(img)


def _run_single_lang(image_np, lang: str) -> OcrPage:
    with _borrow_model(lang) as model:
        result = model.ocr(image_np, cls=True)
    lines: list[OcrLine] = []
    confidences: list[float] = []
    # PaddleOCR returns [[ [box, (text, conf)], ... ]]
    for page in result or []:
        for entry in page or []:
            box, (text, conf) = entry[0], entry[1]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(
                OcrLine(
                    text=text,
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                    confidence=float(conf),
                )
            )
            confidences.append(float(conf))
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrPage(lines=lines, mean_confidence=mean_conf, lang=lang)


def run_ocr(image_bytes: bytes, langs: list[str] | None = None) -> OcrPage:
    """Run OCR in each configured language and return the higher-confidence pass."""
    langs = langs or settings.ocr_langs_list
    image_np = _to_numpy(image_bytes)
    best: OcrPage | None = None
    for lang in langs:
        page = _run_single_lang(image_np, lang)
        if best is None or page.mean_confidence > best.mean_confidence:
            best = page
    return best or OcrPage()
