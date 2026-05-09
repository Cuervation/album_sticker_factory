"""Webpage provider using English Wikipedia page image extraction (no downloads)."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WebpageProvider:
    """Discover page lead images from Wikipedia pages."""

    name = "webpage"
    enabled = True

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        allow_internet = bool(payload.get("allow_internet", False))
        if not allow_internet:
            return {"status": "disabled", "provider": self.name, "message": "Internet access disabled by config.", "candidates": []}

        query = str(payload.get("original_query", payload.get("query", ""))).strip()
        if not query:
            return {"status": "ok", "provider": self.name, "message": "Empty query.", "candidates": []}

        max_results = int(payload.get("max_results", 5))
        timeout_seconds = int(payload.get("timeout_seconds", 15))
        user_agent = str(payload.get("user_agent", "album_sticker_factory/0.1 local research tool"))

        response = self.search_wikipedia(query=query, max_results=max_results, timeout_seconds=timeout_seconds, user_agent=user_agent)
        if response["status"] != "ok":
            return {
                "status": "error",
                "provider": self.name,
                "message": "Wikipedia page query failed.",
                "candidates": [],
                "query_variants_tried": 1,
                "tried_queries": [query],
                "error_type": response.get("error_type", "provider_exception"),
                "error_detail": response.get("error_detail", ""),
            }

        candidates = self.parse_candidates(response["data"], query=query, max_results=max_results)
        return {
            "status": "ok",
            "provider": self.name,
            "message": "Webpage query complete.",
            "candidates": candidates,
            "query_variants_tried": 1,
            "tried_queries": [query],
            "had_http_error": False,
            "had_successful_call": True,
            "raw_results_seen": bool(candidates),
        }

    def search_wikipedia(self, query: str, max_results: int, timeout_seconds: int, user_agent: str) -> dict[str, Any]:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "0",
            "gsrlimit": str(max(1, min(max_results, 20))),
            "prop": "pageimages|info",
            "piprop": "original|thumbnail",
            "pithumbsize": "1200",
            "inprop": "url",
        }
        url = f"https://en.wikipedia.org/w/api.php?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            return {"status": "ok", "data": json.loads(raw)}
        except HTTPError as exc:  # pragma: no cover
            return {"status": "error", "error_type": "http_error", "error_detail": str(exc.code), "data": {}}
        except URLError as exc:  # pragma: no cover
            detail = str(getattr(exc, "reason", "") or exc).strip()[:80]
            return {"status": "error", "error_type": "url_error", "error_detail": detail, "data": {}}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error_type": "provider_exception", "error_detail": str(exc).splitlines()[0][:80], "data": {}}

    @staticmethod
    def parse_candidates(raw_json: dict[str, Any], query: str, max_results: int) -> list[dict[str, Any]]:
        pages = raw_json.get("query", {}).get("pages", {}) if isinstance(raw_json, dict) else {}
        out: list[dict[str, Any]] = []
        for page in pages.values():
            source_page = str(page.get("fullurl") or "")
            original = page.get("original") or {}
            thumbnail = page.get("thumbnail") or {}
            image_url = str(original.get("source") or thumbnail.get("source") or "").strip()
            if not image_url:
                continue
            lowered = image_url.lower()
            if lowered.endswith(".svg") or lowered.endswith(".pdf"):
                continue
            width = original.get("width") or thumbnail.get("width")
            height = original.get("height") or thumbnail.get("height")
            out.append(
                {
                    "source_page": source_page,
                    "image_url": image_url,
                    "mime": "",
                    "width": width,
                    "height": height,
                    "license_status": "needs_manual_review",
                    "author": "",
                    "relevance_score": 0.5,
                    "executed_query": query,
                }
            )
        return out[:max_results]
