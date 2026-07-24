"""Parse progress + time-remaining estimation for the document pipeline.

The parser has no cheap way to report true intra-stage percentages (OCR and the
LLM call are opaque black boxes), so progress is modeled as a handful of phases
with a time-based fill inside each. Durations are estimated from document shape
(page count, OCR, text length) using per-op costs tuned for this deployment and
overridable in config. The numbers are deliberately labeled "estimated" in the
UI — they guide expectations, they are not a guarantee.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.config import settings

# Phase order and the progress band each phase occupies. A phase's floor is
# claimed the instant it starts (so a transition always moves the bar forward),
# and time-based fill advances it toward the ceiling within the band.
PHASES = ("queued", "extracting", "reading", "saving", "done", "failed")
_FLOOR = {"queued": 0.02, "extracting": 0.08, "reading": 0.45, "saving": 0.9, "done": 1.0}
_CEIL = {"queued": 0.05, "extracting": 0.45, "reading": 0.9, "saving": 0.98}

_SCAN_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".zip"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _looks_scanned(filename: str, mime: str | None) -> bool:
    mime = (mime or "").lower()
    if "pdf" in mime or mime.startswith("image/") or "zip" in mime:
        return True
    idx = filename.rfind(".")
    return idx != -1 and filename[idx:].lower() in _SCAN_EXTS


def _llm_chars_per_chunk() -> int:
    # Mirrors llm_extract._chunk_text sizing so chunk counts line up.
    return max(1000, settings.llm_num_ctx * 3 - 2000)


def estimate_initial_seconds(
    filename: str, mime: str | None, size_bytes: int, langs_count: int
) -> float:
    """Coarse total-time guess before the document is opened.

    Page count and text length are unknown here, so scans assume a small page
    count and everything assumes a single LLM chunk. Refined after extraction.
    """
    base = settings.parse_est_base_seconds
    llm = settings.parse_est_llm_chunk_seconds
    persist = settings.parse_est_persist_seconds
    if _looks_scanned(filename, mime):
        pages_guess = 2
        ocr = settings.parse_est_ocr_page_seconds * max(1, langs_count) * pages_guess
        return base + ocr + llm + persist
    return base + llm + persist


def estimate_remaining_after_extract(
    elapsed_so_far: float, text_len: int
) -> float:
    """Total-time estimate once extraction (incl. any OCR) is done.

    OCR time is already spent — folded into `elapsed_so_far` — so the estimate
    is actual-time-so-far plus the LLM and persist work still ahead.
    """
    chunks = max(1, math.ceil(text_len / _llm_chars_per_chunk())) if text_len else 1
    llm = settings.parse_est_llm_chunk_seconds * chunks
    persist = settings.parse_est_persist_seconds
    return elapsed_so_far + llm + persist


def new_timing(started_at: datetime, phase: str = "extracting") -> dict:
    return {"started_at": _iso(started_at), "phase": phase, "est_total_seconds": None}


def document_progress(
    status: str, stage_log: dict | None, now: datetime | None = None
) -> dict:
    """Derive {phase, progress, eta_seconds, est_total_seconds, started_at}.

    Tolerant of documents parsed before timing was recorded: falls back to a
    coarse phase from status alone.
    """
    now = now or datetime.now(timezone.utc)
    timing = (stage_log or {}).get("_timing") or {}
    started_at = timing.get("started_at")
    est_total = timing.get("est_total_seconds")
    phase = timing.get("phase")

    if status in ("parsed", "needs_review"):
        return _out("done", 1.0, 0.0, est_total, started_at)
    if status == "failed":
        return _out("failed", None, None, est_total, started_at)

    start_dt = _parse_iso(started_at) if started_at else None
    if status == "pending" or start_dt is None:
        return _out("queued", _FLOOR["queued"], None, est_total, started_at)

    # processing
    phase = phase if phase in _FLOOR else "extracting"
    elapsed = max(0.0, (now - start_dt).total_seconds())
    floor, ceil = _FLOOR[phase], _CEIL.get(phase, 0.98)
    if est_total and est_total > 0:
        progress = min(ceil, max(floor, elapsed / est_total))
        eta = max(0.0, est_total - elapsed)
    else:
        progress, eta = floor, None
    return _out(phase, round(progress, 4), None if eta is None else round(eta), est_total, started_at)


def _out(phase, progress, eta, est_total, started_at) -> dict:
    return {
        "phase": phase,
        "progress": progress,
        "eta_seconds": eta,
        "est_total_seconds": est_total,
        "started_at": started_at,
    }
