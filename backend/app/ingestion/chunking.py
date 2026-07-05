"""Shared text chunker for embedding pipelines (library docs, quote docs, tenders)."""
from __future__ import annotations


def chunk_text(text: str, max_chars: int = 8000) -> list[str]:
    """Split text into chunks, preferring newline boundaries. Empty-safe."""
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks
