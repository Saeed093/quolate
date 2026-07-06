"""Web access seam for the chat tools (search + URL fetch).

Zero-cost: DuckDuckGo HTML search via `ddgs` and readability extraction via
`trafilatura`. Tests inject a fake client with `set_web_client`.

# TODO(cloud): swap for a hosted search API behind the same interface.
"""
from __future__ import annotations

from typing import Protocol

from app.config import settings

FETCH_CHAR_CAP = 8000


class WebClient(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        ...

    def fetch(self, url: str, max_chars: int = FETCH_CHAR_CAP) -> str:
        ...


class DefaultWebClient:
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        from ddgs import DDGS

        results: list[dict] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    {
                        "title": r.get("title"),
                        "snippet": r.get("body"),
                        "url": r.get("href") or r.get("url"),
                    }
                )
        return results[:max_results]

    def fetch(self, url: str, max_chars: int = FETCH_CHAR_CAP) -> str:
        import httpx
        import trafilatura

        headers = {"User-Agent": settings.scrape_user_agent}
        with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
        text = trafilatura.extract(html) or ""
        return text[:max_chars]


_override: WebClient | None = None


def set_web_client(client: WebClient | None) -> None:
    global _override
    _override = client


def get_web_client() -> WebClient:
    return _override if _override is not None else DefaultWebClient()
