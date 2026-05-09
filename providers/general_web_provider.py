"""General web provider using Wikipedia page search + pageimages (no downloads)."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.provider_query_adapter import build_provider_queries


class GeneralWebProvider:
    """Discover image candidates from Wikipedia search pages."""

    name = "general_web"
    enabled = True

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        allow_internet = bool(payload.get("allow_internet", False))
        if not allow_internet:
            return {"status": "disabled", "provider": self.name, "message": "Internet access disabled by config.", "candidates": []}

        original_query = str(payload.get("original_query", payload.get("query", ""))).strip()
        if not original_query:
            return {"status": "ok", "provider": self.name, "message": "Empty query.", "candidates": []}

        max_results = int(payload.get("max_results", 5))
        timeout_seconds = int(payload.get("timeout_seconds", 15))
        user_agent = str(payload.get("user_agent", "album_sticker_factory/0.1 local research tool"))
        max_query_variants = int(payload.get("max_query_variants", 5))
        include_english_variants = bool(payload.get("include_english_variants", True))
        variants = payload.get("query_variants")
        if not isinstance(variants, list) or not variants:
            variants = build_provider_queries(
                provider=self.name,
                original_query=original_query,
                target_name=payload.get("target_name"),
                chapter_title=payload.get("chapter_title"),
                category=payload.get("category"),
                max_variants=max_query_variants,
                include_english_variants=include_english_variants,
            )
        if not variants:
            variants = [original_query]

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        tried_queries: list[str] = []
        had_http_error = False
        had_successful_call = False
        last_error_type = "provider_exception"
        last_error_detail = ""

        for variant in variants[:max_query_variants]:
            tried_queries.append(variant)
            response = self.search_wikipedia(
                query=variant,
                max_results=max_results,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
            if response["status"] != "ok":
                had_http_error = True
                last_error_type = str(response.get("error_type", "provider_exception"))
                last_error_detail = str(response.get("error_detail", ""))
                continue
            had_successful_call = True
            parsed = self.parse_candidates(query=variant, raw_json=response["data"], max_results=max_results, executed_query=variant)
            for item in parsed:
                fingerprint = f"{item.get('image_url') or ''}|{item.get('source_page') or ''}"
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                candidates.append(item)
            if parsed:
                break

        if not had_successful_call and had_http_error:
            return {
                "status": "error",
                "provider": self.name,
                "message": "HTTP error during Wikipedia query variants.",
                "candidates": [],
                "query_variants_tried": len(tried_queries),
                "tried_queries": tried_queries,
                "error_type": last_error_type,
                "error_detail": last_error_detail,
            }

        return {
            "status": "ok",
            "provider": self.name,
            "message": "Wikipedia query complete.",
            "candidates": candidates,
            "query_variants_tried": len(tried_queries),
            "tried_queries": tried_queries,
            "had_http_error": had_http_error,
            "had_successful_call": had_successful_call,
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
        url = f"https://es.wikipedia.org/w/api.php?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return {"status": "ok", "message": "ok", "data": data}
        except HTTPError as exc:  # pragma: no cover
            return {"status": "error", "error_type": "http_error", "error_detail": str(exc.code), "data": {}}
        except URLError as exc:  # pragma: no cover
            detail = str(getattr(exc, "reason", "") or exc).strip()[:80]
            return {"status": "error", "error_type": "url_error", "error_detail": detail, "data": {}}
        except json.JSONDecodeError as exc:  # pragma: no cover
            return {"status": "error", "error_type": "json_error", "error_detail": str(exc).splitlines()[0][:80], "data": {}}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error_type": "provider_exception", "error_detail": str(exc).splitlines()[0][:80], "data": {}}

    def parse_candidates(self, query: str, raw_json: dict[str, Any], max_results: int, executed_query: str) -> list[dict[str, Any]]:
        pages = raw_json.get("query", {}).get("pages", {}) if isinstance(raw_json, dict) else {}
        out: list[dict[str, Any]] = []
        for page in pages.values():
            title = str(page.get("title") or "")
            source_page = str(page.get("fullurl") or "")
            original = page.get("original") or {}
            thumbnail = page.get("thumbnail") or {}
            image_url = str(original.get("source") or thumbnail.get("source") or "").strip()
            if not image_url:
                continue
            mime = self._mime_from_url(image_url)
            if not mime.startswith("image/"):
                continue
            width = original.get("width") or thumbnail.get("width")
            height = original.get("height") or thumbnail.get("height")
            relevance_score = self.relevance_score(query=query, text=f"{title} {source_page}")
            out.append(
                {
                    "source_page": source_page,
                    "image_url": image_url,
                    "mime": mime,
                    "width": width,
                    "height": height,
                    "license_status": "needs_manual_review",
                    "author": "",
                    "relevance_score": relevance_score,
                    "executed_query": executed_query,
                }
            )
        out.sort(key=lambda item: (item["relevance_score"] if item["relevance_score"] is not None else 0), reverse=True)
        return out[:max_results]

    def relevance_score(self, query: str, text: str) -> float:
        q_tokens = self._tokenize(query)
        t_tokens = self._tokenize(text)
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens)
        return round(min(1.0, overlap / max(1, min(len(q_tokens), len(t_tokens)))), 4)

    @staticmethod
    def _mime_from_url(url: str) -> str:
        lowered = url.lower().split("?")[0]
        if lowered.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lowered.endswith(".png"):
            return "image/png"
        if lowered.endswith(".webp"):
            return "image/webp"
        if lowered.endswith(".gif"):
            return "image/gif"
        if lowered.endswith(".svg"):
            return "image/svg+xml"
        return ""

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        normalized = (
            unicodedata.normalize("NFKD", str(text or ""))
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        tokens = re.findall(r"[a-z0-9]+", normalized)
        return {t for t in tokens if len(t) >= 2}
