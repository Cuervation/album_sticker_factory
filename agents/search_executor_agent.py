"""Execute routed provider tasks (local_folder + wikimedia in Prompt 8)."""

from __future__ import annotations

import csv
import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core import db
from core.config import load_config
from core.paths import DB_PATH, IMAGE_CANDIDATES_CSV_PATH, ROOT_DIR, SEARCH_ROUTES_CSV_PATH
from providers.local_folder_provider import LocalFolderProvider
from providers.wikimedia_provider import WikimediaProvider


class SearchExecutorAgent:
    """Executes routed queries for allowed providers and exports candidates."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or IMAGE_CANDIDATES_CSV_PATH)

    def run(self, provider: str = "local_folder", limit: int | None = None) -> dict[str, Any]:
        config = load_config()
        exec_cfg = config.get("search_execution", {})
        if not exec_cfg.get("enabled", True):
            raise ValueError("search_execution.enabled is false.")

        execute_map = exec_cfg.get("execute_providers", {})
        allowed_prompt8 = {"local_folder", "wikimedia"}
        if provider not in allowed_prompt8:
            raise ValueError("Prompt 8 only allows provider=local_folder or provider=wikimedia.")
        if not bool(execute_map.get(provider, False)):
            raise ValueError(f"{provider} execution is disabled in config.")

        # Reject accidentally enabled unsupported providers in this prompt.
        for provider_name, enabled in execute_map.items():
            if provider_name not in allowed_prompt8 and bool(enabled):
                raise ValueError(
                    f"Provider '{provider_name}' is not allowed in Prompt 8. Disable external providers."
                )

        search_max = int(exec_cfg.get("max_routes_per_run", 20))
        requested_limit = limit if limit is not None else search_max
        effective_limit = requested_limit
        effective_limit = min(effective_limit, search_max)
        if effective_limit <= 0:
            raise ValueError("Route limit must be positive.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            if db.count_rows(conn, "search_routes") == 0:
                raise ValueError("No search routes found. Primero ejecuta python main.py route-search")

            routes = db.list_search_routes_with_context(
                conn=conn,
                provider=provider,
                statuses=("pending", "skipped", "failed"),
                limit=effective_limit,
            )
            if not routes:
                existing_rows = db.list_image_candidates(conn)
                db.export_search_routes_csv(conn, SEARCH_ROUTES_CSV_PATH)
                self._export_candidates_csv(existing_rows)
                return {
                    "status": "ok",
                    "provider": provider,
                    "requested_limit": requested_limit,
                    "effective_limit": effective_limit,
                    "routes_read": 0,
                    "routes_executed": 0,
                    "images_found": 0,
                    "candidates_created": 0,
                    "routes_routed": 0,
                    "routes_skipped": 0,
                    "routes_failed": 0,
                    "csv_path": str(self.output_csv_path),
                    "message": (
                        f"No {provider} routes available. "
                        f"Adjust routing config and run python main.py route-search."
                    ),
                }

            if provider == "local_folder":
                result = self._execute_local_folder(conn=conn, routes=routes, config=config)
            else:
                result = self._execute_wikimedia(conn=conn, routes=routes, config=config)

            exported_rows = db.list_image_candidates(conn)
            db.export_search_routes_csv(conn, SEARCH_ROUTES_CSV_PATH)
        finally:
            conn.close()

        self._export_candidates_csv(exported_rows)
        result["csv_path"] = str(self.output_csv_path)
        result["requested_limit"] = requested_limit
        result["effective_limit"] = effective_limit
        result["search_routes_csv_path"] = str(SEARCH_ROUTES_CSV_PATH)
        return result

    def _execute_local_folder(
        self, conn: Any, routes: list[dict[str, Any]], config: dict[str, Any]
    ) -> dict[str, Any]:
        local_cfg = config.get("local_sources", {})
        local_dir_rel = local_cfg.get("local_images_dir", "input/local_images")
        local_dir = ROOT_DIR / local_dir_rel
        allowed_extensions = local_cfg.get("allowed_extensions", [".jpg", ".jpeg", ".png", ".webp"])

        provider_impl = LocalFolderProvider()
        route_outcomes: dict[str, tuple[str, str]] = {}
        candidate_rows: list[dict[str, Any]] = []
        images_found = 0
        routes_executed = 0

        for route in routes:
            routes_executed += 1
            try:
                response = provider_impl.run(
                    {
                        "base_dir": local_dir,
                        "allowed_extensions": allowed_extensions,
                        "route": route,
                    }
                )
                matches = response.get("matches", [])
                images_found = max(images_found, int(response.get("files_found", 0)))
                if matches:
                    route_outcomes[route["route_id"]] = ("routed", f"candidates_found:{len(matches)}")
                else:
                    route_outcomes[route["route_id"]] = ("skipped", "no_results")

                for match in matches:
                    absolute_path = Path(match["path"]).resolve()
                    try:
                        rel_path = absolute_path.relative_to(ROOT_DIR.resolve())
                    except ValueError:
                        rel_path = absolute_path
                    candidate_rows.append(
                        {
                            "image_id": self._build_image_id(
                                sticker_id=route["sticker_id"],
                                provider_slug="local-folder",
                                fingerprint=f"{route['query_id']}|{str(rel_path).replace('\\', '/')}",
                            ),
                            "sticker_id": route["sticker_id"],
                            "query_id": route["query_id"],
                            "provider": "local_folder",
                            "source_page": "",
                            "image_url": "",
                            "local_path": str(rel_path).replace("\\", "/"),
                            "executed_query": route["query"],
                            "width": None,
                            "height": None,
                            "quality_score": None,
                            "relevance_score": float(match["relevance_score"]),
                            "duplicate_group": None,
                            "license_status": "needs_manual_review",
                            "status": "found",
                        }
                    )
            except Exception as exc:
                detail = str(exc).splitlines()[0][:80]
                route_outcomes[route["route_id"]] = ("failed", f"provider_exception:{detail}")

        created_count = db.upsert_image_candidates(conn, candidate_rows)
        db.update_search_routes_outcome(conn, route_outcomes)
        return self._build_result_summary(
            provider="local_folder",
            routes=routes,
            routes_executed=routes_executed,
            images_found=images_found,
            candidates_created=created_count,
            outcomes=route_outcomes,
        )

    def _execute_wikimedia(
        self, conn: Any, routes: list[dict[str, Any]], config: dict[str, Any]
    ) -> dict[str, Any]:
        ext_cfg = config.get("external_search", {})
        if not ext_cfg.get("enabled", False):
            raise ValueError("external_search.enabled is false.")
        if not ext_cfg.get("allow_internet", False):
            raise ValueError("external_search.allow_internet is false.")
        allowed_real = set(ext_cfg.get("allowed_real_providers", []))
        if "wikimedia" not in allowed_real:
            raise ValueError("wikimedia is not listed in external_search.allowed_real_providers.")

        timeout_seconds = int(ext_cfg.get("timeout_seconds", 15))
        user_agent = str(ext_cfg.get("user_agent", "album_sticker_factory/0.1 local research tool"))
        max_results = int(ext_cfg.get("max_results_per_route", 5))
        if max_results <= 0:
            raise ValueError("external_search.max_results_per_route must be positive.")

        ext_routes_limit = int(ext_cfg.get("max_routes_per_run", len(routes)))
        if ext_routes_limit <= 0:
            raise ValueError("external_search.max_routes_per_run must be positive.")
        routes = routes[:ext_routes_limit]

        provider_impl = WikimediaProvider()
        route_outcomes: dict[str, tuple[str, str]] = {}
        candidate_rows: list[dict[str, Any]] = []
        routes_executed = 0
        query_variants_tried = 0
        executed_query_examples: list[str] = []
        wikimedia_cfg = config.get("wikimedia", {})
        max_query_variants = int(wikimedia_cfg.get("max_query_variants_per_route", 5))
        stop_after_first_success = bool(wikimedia_cfg.get("stop_after_first_success", True))
        include_english_variants = bool(wikimedia_cfg.get("include_english_variants", True))

        for route in routes:
            routes_executed += 1
            response = provider_impl.run(
                {
                    "allow_internet": True,
                    "original_query": route["query"],
                    "target_name": route.get("target_name"),
                    "chapter_title": route.get("chapter_title"),
                    "category": route.get("category"),
                    "max_query_variants": max_query_variants,
                    "stop_after_first_success": stop_after_first_success,
                    "include_english_variants": include_english_variants,
                    "max_results": max_results,
                    "timeout_seconds": timeout_seconds,
                    "user_agent": user_agent,
                }
            )
            query_variants_tried += int(response.get("query_variants_tried", 0))
            used_queries = response.get("tried_queries", [])
            collected: list[dict[str, Any]] = []
            seen_fingerprints: set[str] = set()
            fallback_response: dict[str, Any] | None = None
            unsupported_documentary = False

            status = response.get("status")
            if status == "disabled":
                route_outcomes[route["route_id"]] = ("failed", "disabled_by_config")
                time.sleep(0.2)
                continue
            if status != "ok":
                error_type = str(response.get("error_type", "provider_exception"))
                error_detail = str(response.get("error_detail", "")).strip().replace(";", ",")
                if error_type == "http_error" and error_detail:
                    reason = f"http_error:{error_detail}"
                elif error_type == "url_error" and error_detail:
                    reason = f"url_error:{error_detail}"
                elif error_type == "json_error":
                    reason = "json_error"
                elif error_type == "disabled_by_config":
                    reason = "disabled_by_config"
                elif error_type == "provider_not_allowed":
                    reason = "provider_not_allowed"
                elif error_detail:
                    reason = f"provider_exception:{error_detail}"
                else:
                    reason = "provider_exception:unknown"
                route_outcomes[route["route_id"]] = ("failed", reason)
                time.sleep(0.2)
                continue

            found = response.get("candidates", [])
            if not found:
                fallback_query = self._build_raster_fallback_query(route)
                if fallback_query and fallback_query != route["query"]:
                    fallback_response = provider_impl.run(
                        {
                            "allow_internet": True,
                            "original_query": fallback_query,
                            "target_name": route.get("target_name"),
                            "chapter_title": route.get("chapter_title"),
                            "category": route.get("category"),
                            "max_query_variants": max_query_variants,
                            "stop_after_first_success": stop_after_first_success,
                            "include_english_variants": include_english_variants,
                            "max_results": max_results,
                            "timeout_seconds": timeout_seconds,
                            "user_agent": user_agent,
                        }
                    )
                    query_variants_tried += int(fallback_response.get("query_variants_tried", 0))
                    used_queries = list(used_queries) + list(fallback_response.get("tried_queries", []))
                    if fallback_response.get("status") == "ok":
                        found = fallback_response.get("candidates", [])
                    else:
                        response = fallback_response
            for item in found:
                image_url = str(item.get("image_url", "") or "")
                source_page = str(item.get("source_page", "") or "")
                if not (image_url or source_page):
                    continue
                if image_url and self._is_documentary_url(image_url):
                    unsupported_documentary = True
                    continue
                fingerprint = f"{route['route_id']}|{image_url or source_page}"
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)
                collected.append(
                    {
                        "image_id": self._build_image_id(
                            sticker_id=route["sticker_id"],
                            provider_slug="wikimedia",
                            fingerprint=fingerprint,
                        ),
                        "sticker_id": route["sticker_id"],
                        "query_id": route["query_id"],
                        "provider": "wikimedia",
                        "source_page": source_page,
                        "image_url": image_url,
                        "local_path": "",
                        "executed_query": str(item.get("executed_query", "")),
                        "width": item.get("width"),
                        "height": item.get("height"),
                        "quality_score": None,
                        "relevance_score": item.get("relevance_score", 0.0),
                        "duplicate_group": None,
                        "license_status": item.get("license_status", "needs_manual_review"),
                        "status": "found",
                    }
                )

            if collected:
                first_query = (collected[0].get("executed_query") or "").replace(";", ",")
                route_outcomes[route["route_id"]] = (
                    "routed",
                    f"candidates_found:{len(collected)};executed_query:{first_query}",
                )
                if first_query and len(executed_query_examples) < 5:
                    executed_query_examples.append(first_query)
                candidate_rows.extend(collected)
            else:
                source_resp = fallback_response or response
                if bool(source_resp.get("had_http_error", False)) and not bool(
                    source_resp.get("had_successful_call", False)
                ):
                    route_outcomes[route["route_id"]] = ("failed", "http_error")
                elif bool(source_resp.get("raw_results_seen", False)):
                    unsupported_seen = self._response_has_only_unsupported_mime(source_resp)
                    route_outcomes[route["route_id"]] = (
                        "skipped",
                        (
                            f"raw_results_but_only_unsupported_mime;tried_queries:{len(used_queries)}"
                            if unsupported_seen or unsupported_documentary
                            else f"no_candidates_after_parse;tried_queries:{len(used_queries)}"
                        ),
                    )
                elif unsupported_documentary:
                    route_outcomes[route["route_id"]] = (
                        "skipped",
                        f"raw_results_but_only_unsupported_mime;tried_queries:{len(used_queries)}",
                    )
                else:
                    route_outcomes[route["route_id"]] = (
                        "skipped",
                        f"no_results;tried_queries:{len(used_queries)}",
                    )
            time.sleep(0.2)

        created_count = db.upsert_image_candidates(conn, candidate_rows)
        db.update_search_routes_outcome(conn, route_outcomes)
        return self._build_result_summary(
            provider="wikimedia",
            routes=routes,
            routes_executed=routes_executed,
            images_found=0,
            candidates_created=created_count,
            outcomes=route_outcomes,
            query_variants_tried=query_variants_tried,
            executed_query_examples=executed_query_examples,
        )

    def _build_result_summary(
        self,
        provider: str,
        routes: list[dict[str, Any]],
        routes_executed: int,
        images_found: int,
        candidates_created: int,
        outcomes: dict[str, tuple[str, str]],
        query_variants_tried: int = 0,
        executed_query_examples: list[str] | None = None,
    ) -> dict[str, Any]:
        routed = sum(1 for status, _ in outcomes.values() if status == "routed")
        skipped = sum(1 for status, _ in outcomes.values() if status == "skipped")
        failed = sum(1 for status, _ in outcomes.values() if status == "failed")
        return {
            "status": "ok",
            "provider": provider,
            "routes_read": len(routes),
            "routes_executed": routes_executed,
            "images_found": images_found,
            "candidates_created": candidates_created,
            "routes_routed": routed,
            "routes_skipped": skipped,
            "routes_failed": failed,
            "query_variants_tried": query_variants_tried,
            "executed_query_examples": executed_query_examples or [],
        }

    def _export_candidates_csv(self, rows: list[dict[str, Any]]) -> None:
        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "image_id",
            "sticker_id",
            "query_id",
            "provider",
            "source_page",
            "image_url",
            "local_path",
            "width",
            "height",
            "quality_score",
            "relevance_score",
            "duplicate_group",
            "license_status",
            "status",
            "executed_query",
            "metadata_score",
            "decision_reason",
            "evaluated_at",
            "file_sha256",
            "file_size_bytes",
            "downloaded_at",
            "download_error",
            "preflight_status",
            "preflight_error",
            "preflight_content_type",
            "preflight_content_length",
            "preflight_checked_at",
            "preflight_retry_count",
            "preflight_last_retry_at",
            "retry_requested_at",
            "retry_requested_reason",
            "retry_forced_at",
            "retry_forced_reason",
            "last_retry_mode",
        ]
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _build_image_id(sticker_id: str, provider_slug: str, fingerprint: str) -> str:
        digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:8]
        return f"IMG-{sticker_id}-{provider_slug}-{digest}"

    @staticmethod
    def _is_documentary_url(image_url: str) -> bool:
        path = urlparse(image_url or "").path.lower()
        return path.endswith((".djvu", ".pdf", ".tif", ".tiff", ".svg"))

    @staticmethod
    def _build_raster_fallback_query(route: dict[str, Any]) -> str:
        parts = [
            str(route.get("target_name") or "").strip(),
            str(route.get("chapter_title") or "").strip(),
            "San Lorenzo",
            "foto",
            "imagen",
        ]
        parts = [part for part in parts if part]
        query = " ".join(parts)
        return " ".join(query.split())

    @staticmethod
    def _response_has_only_unsupported_mime(response: dict[str, Any]) -> bool:
        candidates = response.get("candidates", []) if isinstance(response, dict) else []
        for item in candidates:
            mime = str(item.get("mime") or "").strip().lower()
            if mime in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                return False
        return bool(candidates) or bool(response.get("unsupported_mime_seen", False))
