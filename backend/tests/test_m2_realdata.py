"""Runs extraction over whatever real docs the founders drop in ../testdata.

Run with: pytest -m realdata  (OCR must be installed for scanned inputs).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.extract import extract_content

_TESTDATA = Path(__file__).resolve().parents[2] / "testdata"

_SUPPORTED = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".xlsx", ".xls", ".csv", ".eml", ".txt", ".zip",
}


def _real_files() -> list[Path]:
    if not _TESTDATA.exists():
        return []
    return [
        p
        for p in _TESTDATA.rglob("*")
        if p.is_file() and p.suffix.lower() in _SUPPORTED
    ]


@pytest.mark.realdata
@pytest.mark.parametrize("path", _real_files(), ids=lambda p: p.name)
def test_realdata_extracts_without_crashing(path: Path):
    data = path.read_bytes()
    content = extract_content(path.name, None, data)
    assert content.page_count >= 1
    # At least produce some text OR OCR lines for a non-empty file.
    assert content.full_text is not None
