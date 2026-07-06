"""Adapter base class + shared HTML-table parsing.

Adapters separate *parsing* (pure, testable against saved HTML snapshots) from
*fetching* (network I/O). Tests only exercise the pure parse methods.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.config import settings


@dataclass
class NoticeRef:
    tender_no: str | None = None
    title: str | None = None
    detail_url: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class NoticeData:
    tender_no: str | None = None
    title: str | None = None
    organization: str | None = None
    category: str | None = None
    city: str | None = None
    closing_date: date | None = None
    advertise_date: date | None = None
    estimated_value: float | None = None
    raw_text: str = ""
    items: list[str] = field(default_factory=list)
    attachment_bytes: bytes | None = None
    attachment_name: str | None = None
    corrigendum_of_tender_no: str | None = None
    detail_url: str | None = None  # absolute URL of the notice detail page


_DATE_FORMATS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
]

_AMENDMENT_RE = re.compile(r"corrigend|amend|addendum|extension", re.IGNORECASE)

# Trailing time-of-day suffix, e.g. "Jul 20, 2026 01:30 PM".
_TIME_SUFFIX_RE = re.compile(r"\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\s*$", re.IGNORECASE)


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = " ".join(text.split())
    candidates = [text]
    stripped = _TIME_SUFFIX_RE.sub("", text).strip()
    if stripped and stripped != text:
        candidates.append(stripped)
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


_COLUMN_ALIASES = {
    "tender_no": {"tender no", "tender no.", "tender number", "ref", "ref no", "reference", "tender id"},
    "title": {"title", "subject", "description", "tender title", "brief description", "work"},
    "organization": {"organization", "organisation", "department", "agency", "procuring agency", "office"},
    "closing_date": {"closing date", "closing", "due date", "submission date", "last date"},
    "advertise_date": {"advertised date", "advertise date", "advertised", "published", "publish date", "date"},
    "city": {"city", "location", "station"},
}

# Substring fallback when a header doesn't exactly match an alias
# (e.g. EPMS uses "Tender Details" / "Organization Details").
# Order matters: organization must come before title, since a header like
# "Organization Details" contains "detail".
_HEADER_FALLBACK: list[tuple[str, tuple[str, ...]]] = [
    ("tender_no", ("tender no", "tender number", "ref no", "reference no")),
    ("closing_date", ("closing", "due date", "last date", "submission")),
    ("advertise_date", ("advertis", "publish")),
    ("organization", ("organi", "department", "agency")),
    ("title", ("title", "detail", "description", "subject")),
    ("city", ("city", "location")),
]


def _classify_header(cell: str) -> str | None:
    c = cell.strip().lower()
    for field_name, aliases in _COLUMN_ALIASES.items():
        if c in aliases:
            return field_name
    for field_name, needles in _HEADER_FALLBACK:
        if any(n in c for n in needles):
            return field_name
    return None


def _cell_text(cell) -> str:
    """Cell text with duplicate/truncated-repeat segments removed.

    Sites often render a truncated visible span plus the full text (tooltip)
    in the same cell; naive get_text() then duplicates the content.
    """
    parts: list[str] = []
    for t in cell.stripped_strings:
        t = " ".join(t.split())
        if not t:
            continue
        t_norm = t.rstrip(". …")
        replaced = False
        skip = False
        for i, kept in enumerate(parts):
            if t_norm and t_norm in kept:
                skip = True
                break
            if kept.rstrip(". …") in t:
                parts[i] = t
                replaced = True
                break
        if not skip and not replaced:
            parts.append(t)
    return " ".join(parts)


class BaseAdapter:
    """Default adapter: parse the largest HTML table into notices."""

    name: str = "base"
    default_org_type: str = "other"

    def __init__(self, base_url: str, http=None) -> None:
        self.base_url = base_url
        self._http = http

    # ---- pure parsing (tested against snapshots) ----
    def parse_listing(self, html: str) -> list[NoticeRef]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return []
        table = max(tables, key=lambda t: len(t.find_all("tr")))
        rows = table.find_all("tr")
        if not rows:
            return []

        # Header mapping from the first row.
        header_cells = rows[0].find_all(["th", "td"])
        col_map: dict[int, str] = {}
        for idx, cell in enumerate(header_cells):
            field_name = _classify_header(cell.get_text(strip=True))
            if field_name:
                col_map[idx] = field_name
        start = 1 if col_map else 0

        refs: list[NoticeRef] = []
        for row in rows[start:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            values: dict[str, str] = {}
            detail_url = None
            for idx, cell in enumerate(cells):
                key = col_map.get(idx)
                text = _cell_text(cell)
                if key:
                    values[key] = text
                link = cell.find("a", href=True)
                if link and detail_url is None:
                    detail_url = link["href"]
            if not col_map:
                # Positional fallback: tender_no, title, org, closing.
                texts = [_cell_text(c) for c in cells]
                for pos, key in enumerate(
                    ["tender_no", "title", "organization", "closing_date"]
                ):
                    if pos < len(texts):
                        values.setdefault(key, texts[pos])
            if not any(values.values()):
                continue
            refs.append(
                NoticeRef(
                    tender_no=values.get("tender_no") or None,
                    title=values.get("title") or None,
                    detail_url=detail_url,
                    raw=values,
                )
            )
        return refs

    def _detail_url(self, ref: NoticeRef) -> str | None:
        if not ref.detail_url:
            return None
        from urllib.parse import urljoin

        return urljoin(self.base_url, ref.detail_url)

    def parse_notice(self, html: str, ref: NoticeRef) -> NoticeData:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        raw = ref.raw or {}
        title = ref.title or raw.get("title")
        return NoticeData(
            tender_no=ref.tender_no or raw.get("tender_no"),
            title=title,
            organization=raw.get("organization"),
            category=raw.get("category"),
            city=raw.get("city"),
            closing_date=parse_date(raw.get("closing_date")),
            advertise_date=parse_date(raw.get("advertise_date")),
            raw_text=text or (title or ""),
            corrigendum_of_tender_no=self._detect_corrigendum(title, text),
            detail_url=self._detail_url(ref),
        )

    def notice_from_ref(self, ref: NoticeRef) -> NoticeData:
        """Build NoticeData directly from a listing row (no detail fetch)."""
        raw = ref.raw or {}
        title = ref.title or raw.get("title")
        parts = [title or "", raw.get("title_extra", ""), raw.get("organization", "")]
        return NoticeData(
            tender_no=ref.tender_no or raw.get("tender_no"),
            title=title,
            organization=raw.get("organization"),
            category=raw.get("category"),
            city=raw.get("city"),
            closing_date=parse_date(raw.get("closing_date")),
            advertise_date=parse_date(raw.get("advertise_date")),
            raw_text="\n".join(p for p in parts if p),
            corrigendum_of_tender_no=self._detect_corrigendum(title, title or ""),
            detail_url=self._detail_url(ref),
        )

    @staticmethod
    def _detect_corrigendum(title: str | None, text: str) -> str | None:
        """If this looks like an amendment, extract the referenced tender no."""
        blob = f"{title or ''}\n{text or ''}"
        if not _AMENDMENT_RE.search(blob):
            return None
        m = re.search(
            r"(?:of|for|to)\s+(?:tender\s+)?(?:no\.?\s*)?([A-Za-z0-9][A-Za-z0-9\-/]{2,})",
            blob,
            re.IGNORECASE,
        )
        return m.group(1) if m else None

    # ---- network I/O ----
    def _get(self, url: str) -> str:
        import httpx

        headers = {"User-Agent": settings.scrape_user_agent}
        with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    def list_notices(self, since: date | None = None) -> list[NoticeRef]:
        return self.parse_listing(self._get(self.base_url))

    def fetch_notice(self, ref: NoticeRef) -> NoticeData:
        if ref.detail_url:
            from urllib.parse import urljoin

            url = urljoin(self.base_url, ref.detail_url)
            try:
                return self.parse_notice(self._get(url), ref)
            except Exception:
                return self.notice_from_ref(ref)
        return self.notice_from_ref(ref)
