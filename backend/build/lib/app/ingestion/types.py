"""Shared ingestion data structures."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ocr import OcrLine


@dataclass
class PageContent:
    page_no: int
    text: str
    ocr_lines: list[OcrLine] = field(default_factory=list)
    ocr_used: bool = False


@dataclass
class ExtractedContent:
    pages: list[PageContent] = field(default_factory=list)
    ocr_used: bool = False
    kind_detail: str = ""  # pdf_text|pdf_ocr|image|xlsx|csv|whatsapp|email|text

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)
