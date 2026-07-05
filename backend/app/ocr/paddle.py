"""PaddleOCR wrapper: lazy-loaded, English + Chinese passes, keep bboxes.

Picks the pass with higher mean confidence per image. Real PaddleOCR is only
imported on first use (heavy); tests monkeypatch `run_ocr`.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from app.config import settings

_MODELS: dict[str, object] = {}


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


def _get_model(lang: str):
    if lang not in _MODELS:
        from paddleocr import PaddleOCR  # heavy import, lazy

        _MODELS[lang] = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
    return _MODELS[lang]


def _to_numpy(image_bytes: bytes):
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(img)


def _run_single_lang(image_np, lang: str) -> OcrPage:
    model = _get_model(lang)
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
