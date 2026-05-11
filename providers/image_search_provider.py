"""Image search provider backed by configurable search engines.

The provider keeps the existing `image_search` interface, but the engine
selection is now configurable. By default it tries Google Images first and can
fall back to Bing, DuckDuckGo and Openverse without downloading images.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from core.config import load_config
from core.provider_query_adapter import build_provider_queries

DOCUMENTARY_EXTENSIONS = {".pdf", ".djvu", ".tif", ".tiff"}
DEFAULT_ENGINE_ORDER = ["google", "bing", "duckduckgo", "openverse"]
DEFAULT_SEARCH_ENGINES: dict[str, dict[str, Any]] = {
    "google": {
        "enabled": True,
        "kind": "google_images",
        "endpoint": "https://www.google.com/search",
        "params": {"tbm": "isch", "safe": "off", "hl": "es", "gl": "ar"},
    },
    "bing": {
        "enabled": True,
        "kind": "bing_images",
        "endpoint": "https://www.bing.com/images/search",
        "params": {"first": "1", "safeSearch": "off", "setlang": "es-AR"},
    },
    "duckduckgo": {
        "enabled": True,
        "kind": "duckduckgo_images",
        "endpoint": "https://duckduckgo.com/",
        "params": {"iax": "images", "ia": "images"},
    },
    "openverse": {
        "enabled": True,
        "kind": "openverse",
    },
}


class ImageSearchProvider:
    """Discover image candidates from Google-first configurable search engines."""

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

        search_cfg = self._load_search_engine_config(payload)
        max_results = int(payload.get("max_results", search_cfg.get("max_results_per_route", 5)))
        timeout_seconds = int(payload.get("timeout_seconds", search_cfg.get("timeout_seconds", 15)))
        user_agent = str(payload.get("user_agent", search_cfg.get("user_agent", "album_sticker_factory/0.1 local research tool")))
        max_query_variants = int(
            payload.get(
                "max_query_variants",
                search_cfg.get("max_query_variants_per_route", search_cfg.get("max_query_variants", 5)),
            )
        )
        include_english_variants = bool(
            payload.get("include_english_variants", search_cfg.get("include_english_variants", True))
        )
        stop_after_first_engine = bool(search_cfg.get("stop_after_first_engine_with_results", True))
        engines = self._enabled_engines(search_cfg)
        if not engines:
            return {
                "status": "disabled",
                "provider": self.name,
                "message": "No search engines enabled.",
                "candidates": [],
            }

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
        tried_engines: list[str] = []
        had_http_error = False
        had_successful_call = False
        raw_results_seen = False
        last_error_type = "provider_exception"
        last_error_detail = ""

        for variant in variants[:max_query_variants]:
            found_for_variant = False
            for engine_name, engine_cfg in engines:
                tried_queries.append(variant)
                tried_engines.append(engine_name)
                response = self.search_engine(
                    engine_name=engine_name,
                    engine_cfg=engine_cfg,
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
                raw_results_seen = raw_results_seen or bool(response.get("raw_results_seen", False))
                parsed = list(response.get("candidates", []))[:max_results]
                for item in parsed:
                    fingerprint = self._fingerprint_candidate(item)
                    if not fingerprint or fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    candidates.append(item)
                if parsed:
                    found_for_variant = True
                    if stop_after_first_engine:
                        break
            if found_for_variant:
                break

        if not had_successful_call and had_http_error:
            return {
                "status": "error",
                "provider": self.name,
                "message": "HTTP error during image search engine queries.",
                "candidates": [],
                "query_variants_tried": len(tried_queries),
                "tried_queries": tried_queries,
                "tried_engines": tried_engines,
                "error_type": last_error_type,
                "error_detail": last_error_detail,
            }

        return {
            "status": "ok",
            "provider": self.name,
            "message": "Image search engine query complete.",
            "candidates": candidates[:max_results],
            "query_variants_tried": len(tried_queries),
            "tried_queries": tried_queries,
            "tried_engines": tried_engines,
            "had_http_error": had_http_error,
            "had_successful_call": had_successful_call,
            "raw_results_seen": raw_results_seen or bool(candidates),
        }

    def search_engine(
        self,
        *,
        engine_name: str,
        engine_cfg: dict[str, Any],
        query: str,
        max_results: int,
        timeout_seconds: int,
        user_agent: str,
    ) -> dict[str, Any]:
        """Run one configured engine and return normalized candidates."""
        kind = str(engine_cfg.get("kind") or engine_name).strip().lower()
        if kind == "openverse":
            return self.search_openverse(
                query=query,
                max_results=max_results,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
                engine_name=engine_name,
            )
        return self.search_html_image_engine(
            engine_name=engine_name,
            engine_cfg=engine_cfg,
            query=query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )

    def search_html_image_engine(
        self,
        *,
        engine_name: str,
        engine_cfg: dict[str, Any],
        query: str,
        max_results: int,
        timeout_seconds: int,
        user_agent: str,
    ) -> dict[str, Any]:
        url = self._build_engine_url(engine_cfg=engine_cfg, query=query)
        req = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
            },
        )
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            candidates = self.parse_html_candidates(
                html_text=raw,
                query=query,
                engine_name=engine_name,
                engine_cfg=engine_cfg,
                max_results=max_results,
                executed_query=query,
            )
            return {
                "status": "ok",
                "message": "ok",
                "candidates": candidates,
                "raw_results_seen": bool(raw),
            }
        except HTTPError as exc:  # pragma: no cover - network failure path
            return {"status": "error", "error_type": "http_error", "error_detail": str(exc.code), "candidates": []}
        except URLError as exc:  # pragma: no cover - network failure path
            detail = str(getattr(exc, "reason", "") or exc).strip()[:120]
            return {"status": "error", "error_type": "url_error", "error_detail": detail, "candidates": []}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error_type": "provider_exception", "error_detail": str(exc).splitlines()[0][:120], "candidates": []}

    def parse_html_candidates(
        self,
        *,
        html_text: str,
        query: str,
        engine_name: str,
        engine_cfg: dict[str, Any],
        max_results: int,
        executed_query: str,
    ) -> list[dict[str, Any]]:
        patterns = self._image_url_patterns(engine_name=engine_name, engine_cfg=engine_cfg)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
                raw_url = match.groupdict().get("url") or (match.group(1) if match.groups() else "")
                image_url = self._decode_url_candidate(raw_url)
                if not self._is_supported_image_url(image_url):
                    continue
                if image_url in seen:
                    continue
                seen.add(image_url)
                out.append(
                    {
                        "source_page": self._source_page_from_image_url(image_url),
                        "image_url": image_url,
                        "mime": self._mime_from_url(image_url),
                        "width": None,
                        "height": None,
                        "license_status": "needs_manual_review",
                        "author": "",
                        "relevance_score": self.relevance_score(query=query, text=image_url),
                        "executed_query": executed_query,
                        "search_engine": engine_name,
                    }
                )
                if len(out) >= max_results:
                    return out
        return out

    def search_openverse(
        self,
        *,
        query: str,
        max_results: int,
        timeout_seconds: int,
        user_agent: str,
        engine_name: str = "openverse",
    ) -> dict[str, Any]:
        params = {"q": query, "page_size": str(max(1, min(max_results, 20)))}
        url = f"https://api.openverse.org/v1/images/?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            candidates = self.parse_openverse_candidates(
                query=query,
                raw_json=data,
                max_results=max_results,
                executed_query=query,
                engine_name=engine_name,
            )
            return {"status": "ok", "message": "ok", "candidates": candidates, "raw_results_seen": bool(data.get("results"))}
        except HTTPError as exc:  # pragma: no cover - network failure path
            return {"status": "error", "error_type": "http_error", "error_detail": str(exc.code), "candidates": []}
        except URLError as exc:  # pragma: no cover - network failure path
            detail = str(getattr(exc, "reason", "") or exc).strip()[:120]
            return {"status": "error", "error_type": "url_error", "error_detail": detail, "candidates": []}
        except json.JSONDecodeError as exc:  # pragma: no cover
            return {"status": "error", "error_type": "json_error", "error_detail": str(exc).splitlines()[0][:120], "candidates": []}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error_type": "provider_exception", "error_detail": str(exc).splitlines()[0][:120], "candidates": []}

    def parse_openverse_candidates(
        self,
        *,
        query: str,
        raw_json: dict[str, Any],
        max_results: int,
        executed_query: str,
        engine_name: str,
    ) -> list[dict[str, Any]]:
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
            out.append(
                {
                    "source_page": source_page,
                    "image_url": image_url,
                    "mime": mime,
                    "width": row.get("width"),
                    "height": row.get("height"),
                    "license_status": self._license_status(str(row.get("license") or "")),
                    "author": str(row.get("creator") or ""),
                    "relevance_score": self.relevance_score(query=query, text=f"{title} {source_page}"),
                    "executed_query": executed_query,
                    "search_engine": engine_name,
                }
            )
        out.sort(key=lambda item: (item["relevance_score"] if item["relevance_score"] is not None else 0), reverse=True)
        return out[:max_results]

    def _load_search_engine_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload_cfg = payload.get("search_engines")
        if isinstance(payload_cfg, dict):
            return payload_cfg
        try:
            config = load_config()
            cfg = config.get("search_engines", {})
            return cfg if isinstance(cfg, dict) else {}
        except Exception:  # pragma: no cover - defensive fallback for isolated provider tests
            return {}

    def _enabled_engines(self, search_cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        configured_order = search_cfg.get("enabled_order")
        order = [str(item) for item in configured_order] if isinstance(configured_order, list) and configured_order else DEFAULT_ENGINE_ORDER
        providers_cfg = search_cfg.get("providers", {})
        providers = providers_cfg if isinstance(providers_cfg, dict) else {}

        engines: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for engine_name in order:
            engine_cfg = self._merged_engine_config(engine_name, providers.get(engine_name, {}))
            if not engine_cfg.get("enabled", True):
                continue
            engines.append((engine_name, engine_cfg))
            seen.add(engine_name)

        # Extension point: any custom engine not listed in enabled_order is appended.
        for engine_name, raw_cfg in providers.items():
            if engine_name in seen:
                continue
            engine_cfg = self._merged_engine_config(str(engine_name), raw_cfg)
            if not engine_cfg.get("enabled", False):
                continue
            engines.append((str(engine_name), engine_cfg))
        return engines

    @staticmethod
    def _merged_engine_config(engine_name: str, raw_cfg: Any) -> dict[str, Any]:
        base = dict(DEFAULT_SEARCH_ENGINES.get(engine_name, {"enabled": False, "kind": "html_image_search"}))
        if isinstance(raw_cfg, dict):
            merged = {**base, **raw_cfg}
        elif raw_cfg is True:
            merged = {**base, "enabled": True}
        elif raw_cfg is False:
            merged = {**base, "enabled": False}
        else:
            merged = base
        return merged

    @staticmethod
    def _build_engine_url(*, engine_cfg: dict[str, Any], query: str) -> str:
        template = str(engine_cfg.get("url_template") or "").strip()
        encoded_query = quote_plus(query)
        if template:
            return template.replace("{query}", encoded_query)

        endpoint = str(engine_cfg.get("endpoint") or "").strip()
        params = engine_cfg.get("params", {})
        query_param = str(engine_cfg.get("query_param") or "q")
        if not endpoint:
            raise ValueError("search engine endpoint is required.")
        merged_params = dict(params) if isinstance(params, dict) else {}
        merged_params[query_param] = query
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode(merged_params)}"

    @staticmethod
    def _image_url_patterns(*, engine_name: str, engine_cfg: dict[str, Any]) -> list[str]:
        custom_patterns = engine_cfg.get("image_url_patterns")
        if isinstance(custom_patterns, list) and custom_patterns:
            return [str(pattern) for pattern in custom_patterns]

        kind = str(engine_cfg.get("kind") or engine_name).lower()
        if kind == "google_images":
            return [
                r'"ou"\s*:\s*"(?P<url>https?:\\/\\/[^"]+)"',
                r"imgurl=(?P<url>https?%3A%2F%2F[^&\"'>]+)",
            ]
        if kind == "bing_images":
            return [
                r'"murl"\s*:\s*"(?P<url>https?:\\/\\/[^"]+)"',
                r"mediaurl=(?P<url>https?%3A%2F%2F[^&\"'>]+)",
            ]
        if kind == "duckduckgo_images":
            return [
                r'"image"\s*:\s*"(?P<url>https?:\\/\\/[^"]+)"',
                r"uddg=(?P<url>https?%3A%2F%2F[^&\"'>]+)",
            ]
        return [
            r'"(?:image|imageUrl|image_url|thumbnail|url)"\s*:\s*"(?P<url>https?:\\/\\/[^"]+)"',
            r"<img[^>]+src=[\"'](?P<url>https?://[^\"']+)[\"']",
        ]

    @staticmethod
    def _decode_url_candidate(raw_url: str) -> str:
        value = html.unescape(str(raw_url or "")).strip()
        if not value:
            return ""
        value = value.replace("\\/", "/").replace("\\u003d", "=").replace("\\u0026", "&")
        for _ in range(2):
            decoded = unquote(value)
            if decoded == value:
                break
            value = decoded
        return value.strip()

    @staticmethod
    def _source_page_from_image_url(image_url: str) -> str:
        parsed = urlparse(image_url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _is_supported_image_url(self, image_url: str) -> bool:
        if not image_url.startswith(("http://", "https://")):
            return False
        lowered = image_url.lower().split("?", 1)[0]
        if any(lowered.endswith(ext) for ext in DOCUMENTARY_EXTENSIONS):
            return False
        # Google thumbnails are usually too small and unstable; prefer original URLs.
        if "encrypted-tbn" in lowered or "gstatic.com/images?q=tbn" in lowered:
            return False
        mime = self._mime_from_url(image_url)
        if mime and not mime.startswith("image/"):
            return False
        return True

    @staticmethod
    def _fingerprint_candidate(item: dict[str, Any]) -> str:
        return f"{item.get('image_url') or ''}|{item.get('source_page') or ''}"

    def relevance_score(self, query: str, text: str) -> float:
        q_tokens = self._tokenize(query)
        t_tokens = self._tokenize(text)
        if not q_tokens or not t_tokens:
            return 0.5
        overlap = len(q_tokens & t_tokens)
        return round(min(1.0, max(0.1, overlap / max(1, min(len(q_tokens), len(t_tokens))))), 4)

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
        return ImageSearchProvider._mime_from_url(image_url)

    @staticmethod
    def _mime_from_url(url: str) -> str:
        lowered = url.lower().split("?", 1)[0]
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
        if any(lowered.endswith(ext) for ext in DOCUMENTARY_EXTENSIONS):
            return "application/octet-stream"
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
        return {token for token in tokens if len(token) >= 2}
