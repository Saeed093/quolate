"""Generic adapter: LLM-parses an arbitrary listing page.

Created by the user's "Add source" form (name + URL). Fetches static HTML via
httpx and falls back to Playwright (Chromium) for JS-rendered pages, then asks
the LLM to extract notice candidates from the visible text.
"""
from __future__ import annotations

from datetime import date

from app.config import settings
from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError, complete_json
from app.tenders.adapters.base import BaseAdapter, NoticeRef, parse_date

_LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "notices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tender_no": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "organization": {"type": ["string", "null"]},
                    "closing_date": {"type": ["string", "null"]},
                    "city": {"type": ["string", "null"]},
                },
                "required": ["title"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["notices"],
    "additionalProperties": True,
}


class GenericAdapter(BaseAdapter):
    name = "generic"
    default_org_type = "other"

    def parse_listing(self, html: str) -> list[NoticeRef]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        text = text[:12000]
        if not text.strip():
            return []

        client = get_llm_client()
        messages = [
            {
                "role": "system",
                "content": (
                    "You extract public-procurement tender notices from listing "
                    "page text. Return ONLY JSON matching the schema. Each notice "
                    "must have at least a title."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Listing text:\n\"\"\"\n" + text + "\n\"\"\"\n\n"
                    'Return JSON: {"notices": [{"tender_no": str|null, '
                    '"title": str, "organization": str|null, '
                    '"closing_date": str|null, "city": str|null}]}'
                ),
            },
        ]
        try:
            result = complete_json(client, messages, _LISTING_SCHEMA)
        except SchemaEnforceError:
            return []
        if isinstance(result, list):
            result = {"notices": result}

        refs: list[NoticeRef] = []
        for n in result.get("notices", []) or []:
            if not isinstance(n, dict) or not n.get("title"):
                continue
            refs.append(
                NoticeRef(
                    tender_no=n.get("tender_no"),
                    title=n.get("title"),
                    detail_url=None,
                    raw={
                        "organization": n.get("organization"),
                        "closing_date": n.get("closing_date"),
                        "city": n.get("city"),
                    },
                )
            )
        return refs

    def _get(self, url: str) -> str:
        import httpx

        headers = {"User-Agent": settings.scrape_user_agent}
        html = ""
        try:
            with httpx.Client(
                timeout=30, follow_redirects=True, headers=headers
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception:
            html = ""

        if self._looks_js_rendered(html):
            rendered = self._render_with_playwright(url)
            if rendered:
                html = rendered
        return html

    @staticmethod
    def _looks_js_rendered(html: str) -> bool:
        from bs4 import BeautifulSoup

        if not html:
            return True
        text = BeautifulSoup(html, "html.parser").get_text(strip=True)
        markers = ("window.__NEXT_DATA__", "id=\"root\"", "id=\"app\"", "ng-app")
        return len(text) < 400 or any(m in html for m in markers)

    @staticmethod
    def _render_with_playwright(url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=settings.scrape_user_agent)
                page.goto(url, wait_until="networkidle", timeout=30000)
                content = page.content()
                browser.close()
                return content
        except Exception:
            return None

    def list_notices(self, since: date | None = None) -> list[NoticeRef]:
        return self.parse_listing(self._get(self.base_url))

    def fetch_notice(self, ref: NoticeRef):
        return self.notice_from_ref(ref)
