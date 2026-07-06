"""Attach page/bbox provenance to an extracted field via fuzzy snippet match."""
from __future__ import annotations

from rapidfuzz import fuzz

from app.ingestion.types import PageContent

MATCH_THRESHOLD = 80.0  # rapidfuzz score 0..100 (== 0.8 ratio)


def locate_snippet(snippet: str | None, pages: list[PageContent]) -> dict:
    """Return provenance {page, bbox, source_snippet}.

    Fuzzy-matches the snippet to OCR lines (with bboxes) first; falls back to
    substring/fuzzy match against page text (bbox=None) for text-layer PDFs.
    """
    provenance: dict = {"page": None, "bbox": None, "source_snippet": snippet}
    if not snippet or not snippet.strip():
        return provenance

    best_score = 0.0
    best_page: int | None = None
    best_bbox: list[float] | None = None

    for page in pages:
        for line in page.ocr_lines:
            if not line.text.strip():
                continue
            score = fuzz.token_set_ratio(snippet, line.text)
            if score > best_score:
                best_score = score
                best_page = page.page_no
                best_bbox = line.bbox

    if best_score >= MATCH_THRESHOLD and best_page is not None:
        provenance["page"] = best_page
        provenance["bbox"] = best_bbox
        return provenance

    # Fallback for text-layer pages (no OCR bboxes): match against page text.
    best_score = 0.0
    best_page = None
    for page in pages:
        if not page.text.strip():
            continue
        score = fuzz.partial_ratio(snippet, page.text)
        if score > best_score:
            best_score = score
            best_page = page.page_no
    if best_score >= MATCH_THRESHOLD and best_page is not None:
        provenance["page"] = best_page
        provenance["bbox"] = None

    return provenance
