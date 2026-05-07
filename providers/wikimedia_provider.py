"""Wikimedia provider for controlled Commons API discovery (no downloads)."""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.error import HTTPError, URLError
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.provider_query_adapter import build_provider_queries

class WikimediaProvider:
    """Discover image candidates from Wikimedia Commons API."""

    name = "wikimedia"
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
            return {
                "status": "ok",
                "provider": self.name,
                "message": "Empty query.",
                "candidates": [],
            }

        max_results = int(payload.get("max_results", 5))
        timeout_seconds = int(payload.get("timeout_seconds", 15))
        user_agent = str(payload.get("user_agent", "album_sticker_factory/0.1 local research tool"))
        max_query_variants = int(payload.get("max_query_variants", 5))
        include_english_variants = bool(payload.get("include_english_variants", True))
        stop_after_first_success = bool(payload.get("stop_after_first_success", True))
        variants = payload.get("query_variants")
        if not isinstance(variants, list) or not variants:
            variants = build_provider_queries(
                provider="wikimedia",
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
        seen_fingerprints: set[str] = set()
        tried_queries: list[str] = []
        had_http_error = False
        had_successful_call = False
        raw_results_seen = False
        last_error_type = "provider_exception"
        last_error_detail = ""

        for variant in variants[:max_query_variants]:
            tried_queries.append(variant)
            response = self.search_commons(
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
            parsed = self.parse_candidates(
                query=variant,
                raw_json=response["data"],
                max_results=max_results,
                executed_query=variant,
            )
            pages = response.get("data", {}).get("query", {}).get("pages", {})
            if isinstance(pages, dict) and pages:
                raw_results_seen = True
            for item in parsed:
                fingerprint = f"{item.get('image_url') or ''}|{item.get('source_page') or ''}"
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)
                candidates.append(item)
            if parsed and stop_after_first_success:
                break

        if not had_successful_call and had_http_error:
            return {
                "status": "error",
                "provider": self.name,
                "message": "HTTP error during Wikimedia query variants.",
                "candidates": [],
                "query_variants_tried": len(tried_queries),
                "tried_queries": tried_queries,
                "error_type": last_error_type,
                "error_detail": last_error_detail,
            }

        return {
            "status": "ok",
            "provider": self.name,
            "message": "Wikimedia query complete.",
            "candidates": candidates,
            "query_variants_tried": len(tried_queries),
            "tried_queries": tried_queries,
            "had_http_error": had_http_error,
            "had_successful_call": had_successful_call,
            "raw_results_seen": raw_results_seen,
        }

    def search_commons(
        self,
        query: str,
        max_results: int,
        timeout_seconds: int,
        user_agent: str,
    ) -> dict[str, Any]:
        """Call Wikimedia Commons API for file namespace search."""
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(max_results),
            "prop": "imageinfo|info",
            "iiprop": "url|mime|size|extmetadata",
            "inprop": "url",
        }
        url = f"https://commons.wikimedia.org/w/api.php?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": user_agent})
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return {"status": "ok", "message": "ok", "data": data}
        except HTTPError as exc:  # pragma: no cover - network failure path
            return {
                "status": "error",
                "error_type": "http_error",
                "error_detail": str(exc.code),
                "message": f"{exc}",
                "data": {},
            }
        except URLError as exc:  # pragma: no cover - network failure path
            detail = str(getattr(exc, "reason", "") or exc).strip()[:80]
            return {
                "status": "error",
                "error_type": "url_error",
                "error_detail": detail,
                "message": f"{exc}",
                "data": {},
            }
        except json.JSONDecodeError as exc:  # pragma: no cover - malformed response path
            return {
                "status": "error",
                "error_type": "json_error",
                "error_detail": str(exc).splitlines()[0][:80],
                "message": f"{exc}",
                "data": {},
            }
        except Exception as exc:  # pragma: no cover - unexpected path
            return {
                "status": "error",
                "error_type": "provider_exception",
                "error_detail": str(exc).splitlines()[0][:80],
                "message": f"{exc}",
                "data": {},
            }

    def parse_candidates(
        self,
        query: str,
        raw_json: dict[str, Any],
        max_results: int,
        executed_query: str,
    ) -> list[dict[str, Any]]:
        """Parse Commons response into normalized candidate dicts."""
        pages = raw_json.get("query", {}).get("pages", {}) if isinstance(raw_json, dict) else {}
        candidates: list[dict[str, Any]] = []
        for _, page in pages.items():
            imageinfo = (page.get("imageinfo") or [{}])[0]
            source_page = imageinfo.get("descriptionurl") or page.get("canonicalurl") or page.get("fullurl") or ""
            image_url = imageinfo.get("url") or ""
            title = page.get("title", "")
            if not (source_page or image_url):
                continue
            extmetadata = imageinfo.get("extmetadata") or {}
            license_status = self.license_status_from_metadata(extmetadata)
            author = self.extract_author(extmetadata)
            relevance_score = self.relevance_score(query=query, title=title, source_page=source_page)
            candidates.append(
                {
                    "source_page": source_page,
                    "image_url": image_url,
                    "width": imageinfo.get("width"),
                    "height": imageinfo.get("height"),
                    "license_status": license_status,
                    "author": author,
                    "relevance_score": relevance_score,
                    "executed_query": executed_query,
                }
            )
        candidates.sort(key=lambda item: (item["relevance_score"] if item["relevance_score"] is not None else 0), reverse=True)
        return candidates[:max_results]

    def relevance_score(self, query: str, title: str, source_page: str) -> float:
        """Token-overlap score between query and Wikimedia title/page."""
        q_tokens = self.tokenize(query)
        t_tokens = self.tokenize(f"{title} {source_page}")
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens)
        score = overlap / max(1, min(len(q_tokens), len(t_tokens)))
        return round(min(1.0, score), 4)

    def license_status_from_metadata(self, extmetadata: dict[str, Any]) -> str:
        """Best-effort mapping from Commons metadata to local license status."""
        text_parts: list[str] = []
        for key in ("LicenseShortName", "License", "UsageTerms", "Copyrighted", "LicenseUrl"):
            value = extmetadata.get(key, {})
            if isinstance(value, dict):
                val = str(value.get("value", ""))
            else:
                val = str(value)
            text_parts.append(val.casefold())
        license_blob = " ".join(text_parts)
        if "public domain" in license_blob or "cc0" in license_blob:
            return "clear"
        if (
            "creative commons" in license_blob
            or "cc-by" in license_blob
            or "cc by" in license_blob
            or "attribution" in license_blob
        ):
            return "attribution_required"
        if license_blob.strip():
            return "needs_manual_review"
        return "unknown"

    def extract_author(self, extmetadata: dict[str, Any]) -> str:
        """Extract author string from extmetadata if present."""
        author = extmetadata.get("Artist", {})
        if isinstance(author, dict):
            raw = str(author.get("value", ""))
        else:
            raw = str(author)
        raw = re.sub(r"<[^>]+>", " ", raw)
        return " ".join(raw.split())

    def tokenize(self, text: str) -> set[str]:
        """Normalize and tokenize text."""
        normalized = (
            unicodedata.normalize("NFKD", str(text or ""))
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        tokens = re.findall(r"[a-z0-9]+", normalized)
        return {t for t in tokens if len(t) >= 2}

    def search(self, payload: dict | None = None) -> dict:
        """Alias for run()."""
        return self.run(payload)

    def stub(self) -> dict:
        """Stub shape for non-execution contexts."""
        return {
            "status": "not_implemented",
            "provider": self.name,
            "message": "Provider stub only. Real search will be implemented in a later prompt.",
        }
