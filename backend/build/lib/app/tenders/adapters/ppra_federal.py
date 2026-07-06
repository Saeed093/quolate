"""PPRA Federal adapter (EPMS portal, epms.ppra.gov.pk).

The EPMS listing table renders each cell as several text segments (a
truncated visible span plus full text, category chips, sub-organization,
"City - Pakistan"), so this adapter parses the columns precisely instead of
relying on the generic joined-text heuristics.
"""
from __future__ import annotations

import re

from app.tenders.adapters.base import BaseAdapter, NoticeRef, _classify_header

_CITY_RE = re.compile(r"^(.+?)\s*-\s*Pakistan$", re.IGNORECASE)


def _segments(cell) -> list[str]:
    """Unique text segments of a cell (drops truncated repeats)."""
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
    return parts


class PpraFederalAdapter(BaseAdapter):
    name = "ppra_federal"
    default_org_type = "federal"

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

        header_cells = rows[0].find_all(["th", "td"])
        col_map: dict[int, str] = {}
        for idx, cell in enumerate(header_cells):
            field_name = _classify_header(cell.get_text(strip=True))
            if field_name:
                col_map[idx] = field_name
        if not col_map:
            return super().parse_listing(html)

        refs: list[NoticeRef] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            values: dict[str, str] = {}
            detail_url = None
            for idx, cell in enumerate(cells):
                link = cell.find("a", href=True)
                if link and detail_url is None:
                    detail_url = link["href"]
                key = col_map.get(idx)
                if not key:
                    continue
                segs = _segments(cell)
                if not segs:
                    continue
                if key == "title":
                    # First segment is the tender title; the rest are
                    # category/code/organization chips.
                    values["title"] = segs[0]
                    if len(segs) > 1:
                        values["title_extra"] = " | ".join(segs[1:])
                        for seg in segs[1:]:
                            # Category chip: short label with lowercase letters
                            # (reference codes are all-caps/digits, subtitles
                            # are long sentences).
                            if len(seg) <= 40 and any(c.islower() for c in seg):
                                values.setdefault("category", seg)
                                break
                elif key == "organization":
                    org_parts: list[str] = []
                    for seg in segs:
                        m = _CITY_RE.match(seg)
                        if m:
                            values.setdefault("city", m.group(1).strip())
                        else:
                            org_parts.append(seg)
                    values["organization"] = " — ".join(org_parts)
                else:
                    values[key] = " ".join(segs)
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
