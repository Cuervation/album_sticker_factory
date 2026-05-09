"""Image search provider backed by Openverse API (no downloads)."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.provider_query_adapter import build_provider_queries


class ImageSearchProvider:
    """Discover image candidates from Openverse search API."""

    name = "image_search"
    enabled = True

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        allow_internet = bool(payload.get("allow_internet", False))
        if not allow_internet:
            return {
                "status": "disabled",
                "provider": self.name,
                "message": "Internet access disabled by config.",
                "candidates": [],
            }

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
            response = self.search_openverse(
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
                "message": "HTTP error during Openverse query variants.",
                "candidates": [],
                "query_variants_tried": len(tried_queries),
                "tried_queries": tried_queries,
                "error_type": last_error_type,
                "error_detail": last_error_detail,
            }

        return {
            "status": "ok",
            "provider": self.name,
            "message": "Openverse query complete.",
            "candidates": candidates,
            "query_variants_tried": len(tried_queries),
            "tried_queries": tried_queries,
            "had_http_error": had_http_error,
            "had_successful_call": had_successful_call,
            "raw_results_seen": bool(candidates),
        }

    def search_openverse(self, query: str, max_results: int, timeout_seconds: int, user_agent: str) -> dict[str, Any]:
        params = {"q": query, "page_size": str(max(1, min(max_results, 20)))}
        url = f"https://api.openverse.org/v1/images/?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return {"status": "ok", "message": "ok", "data": data}
        except HTTPError as exc:  # pragma: no cover - network failure path
            return {"status": "error", "error_type": "http_error", "error_detail": str(exc.code), "data": {}}
        except URLError as exc:  # pragma: no cover - network failure path
            detail = str(getattr(exc, "reason", "") or exc).strip()[:80]
            return {"status": "error", "error_type": "url_error", "error_detail": detail, "data": {}}
        except json.JSONDecodeError as exc:  # pragma: no cover
            return {"status": "error", "error_type": "json_error", "error_detail": str(exc).splitlines()[0][:80], "data": {}}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error_type": "provider_exception", "error_detail": str(exc).splitlines()[0][:80], "data": {}}

    def parse_candidates(self, query: str, raw_json: dict[str, Any], max_results: int, executed_query: str) -> list[dict[str, Any]]:
        rows = raw_json.get("results", []) if isinstance(raw_json, dict) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            image_url = str(row.get("url") or "").strip()
            source_page = str(row.get("foreign_landing_url") or "").strip()
            if not (image_url or source_page):
                continue
            filetype = str(row.get("filetype") or "").strip().lower()
            mime = self._mime_from_filetype(filetype, image_url)
            if mime and not mime.startswith("image/"):
                continue
            title = str(row.get("title") or "")
            source = str(row.get("source") or row.get("provider") or "openverse")
            relevance_score = self.relevance_score(query=query, title=f"{title} {source_page}")
            out.append(
                {
                    "source_page": source_page,
                    "image_url": image_url,
                    "mime": mime,
                    "width": row.get("width"),
                    "height": row.get("height"),
                    "license_status": self._license_status(str(row.get("license") or "")),
                    "author": str(row.get("creator") or ""),
                    "relevance_score": relevance_score,
                    "executed_query": executed_query,
                }
            )
        out.sort(key=lambda item: (item["relevance_score"] if item["relevance_score"] is not None else 0), reverse=True)
        return out[:max_results]

    def relevance_score(self, query: str, title: str) -> float:
        q_tokens = self._tokenize(query)
        t_tokens = self._tokenize(title)
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens)
        return round(min(1.0, overlap / max(1, min(len(q_tokens), len(t_tokens)))), 4)

    @staticmethod
    def _mime_from_filetype(filetype: str, image_url: str) -> str:
        if filetype:
            normalized = filetype.lower().replace(".", "")
            if normalized in {"jpg", "jpeg"}:
                return "image/jpeg"
            if normalized in {"png"}:
                return "image/png"
            if normalized in {"webp"}:
                return "image/webp"
            if normalized in {"gif"}:
                return "image/gif"
        lowered = image_url.lower()
        if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
            return "image/jpeg"
        if lowered.endswith(".png"):
            return "image/png"
        if lowered.endswith(".webp"):
            return "image/webp"
        if lowered.endswith(".gif"):
            return "image/gif"
        return ""

    @staticmethod
    def _license_status(license_code: str) -> str:
        code = license_code.strip().lower()
        if code in {"cc0", "pdm", "public-domain"}:
            return "clear"
        if code.startswith("cc-") or code in {"by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"}:
            return "attribution_required"
        if code:
            return "needs_manual_review"
        return "unknown"

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
