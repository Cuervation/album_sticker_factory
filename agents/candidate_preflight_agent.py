"""Technical preflight checks for candidate URLs (no full downloads)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core import db
from core.config import load_config
from core.paths import DB_PATH, IMAGE_CANDIDATES_CSV_PATH

ALLOWED_RASTER_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


class CandidatePreflightAgent:
    """Run lightweight HEAD/Range checks on existing candidate URLs."""

    def __init__(self, db_path: Path | str | None = None, output_csv_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or IMAGE_CANDIDATES_CSV_PATH)

    def run(
        self,
        provider: str | None = None,
        limit: int | None = None,
        retry_only: bool = False,
        force: bool = False,
        image_id: str | None = None,
    ) -> dict[str, Any]:
        cfg = load_config().get("candidate_preflight", {})
        if not bool(cfg.get("enabled", True)):
            raise ValueError("candidate_preflight.enabled is false.")
        statuses_to_check = tuple(cfg.get("statuses_to_check", ["needs_review", "approved"]))
        allowed_providers = {str(x) for x in cfg.get("allowed_providers", ["wikimedia"])}
        timeout_seconds = int(cfg.get("timeout_seconds", 15))
        max_per_run = int(cfg.get("max_candidates_per_run", 50))
        max_size_bytes = int(cfg.get("max_file_size_mb", 8)) * 1024 * 1024
        use_head_first = bool(cfg.get("use_head_first", True))
        fallback_to_range_get = bool(cfg.get("fallback_to_range_get", True))
        user_agent = str(cfg.get("user_agent", "album_sticker_factory/0.1 local preflight tool"))
        mark_non_image = bool(cfg.get("mark_non_image_as_technical_rejected", True))
        keep_429_as_retryable = bool(cfg.get("keep_429_as_retryable", True))

        retry_cfg = load_config().get("preflight_retry", {})
        retry_enabled = bool(retry_cfg.get("enabled", True))
        retry_statuses = tuple(retry_cfg.get("statuses_to_retry", ["retryable"]))
        retry_max_per_run = int(retry_cfg.get("max_candidates_per_run", 20))
        min_seconds_between_retries = int(retry_cfg.get("min_seconds_between_retries", 300))
        max_retry_attempts = int(retry_cfg.get("max_retry_attempts", 3))

        effective_limit_default = retry_max_per_run if retry_only else max_per_run
        effective_limit = min(limit if limit is not None else effective_limit_default, effective_limit_default)
        if effective_limit <= 0:
            raise ValueError("Preflight limit must be positive.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            if retry_only:
                candidates = db.list_candidates_for_retry_mark(
                    conn,
                    provider=provider,
                    image_id=image_id,
                    preflight_statuses=retry_statuses,
                    limit=effective_limit,
                )
            else:
                candidates = db.list_candidates_for_preflight(
                    conn,
                    statuses=statuses_to_check,
                    provider=provider,
                    image_id=image_id,
                    limit=effective_limit,
                )
            if not candidates:
                rows = db.list_image_candidates(conn)
                self._export(rows)
                return {
                    "status": "ok",
                    "candidates_read": 0,
                    "checked": 0,
                    "passed": 0,
                    "blocked": 0,
                    "retryable": 0,
                    "failed": 0,
                    "technical_rejected": 0,
                    "csv_path": str(self.output_csv_path),
                    "message": "No hay candidatos para preflight con esos filtros.",
                }

            counts = {
                "checked": 0,
                "passed": 0,
                "blocked": 0,
                "retryable": 0,
                "failed": 0,
                "technical_rejected": 0,
                "skipped_by_max_retry_attempts": 0,
                "skipped_by_retry_window": 0,
                "skipped_by_status": 0,
                "skipped_by_preflight_status": 0,
                "skipped_by_missing_url": 0,
                "skipped_by_other_reason": 0,
                "skipped_by_not_selected_after_mark": 0,
            }
            for candidate in candidates:
                self._process_candidate(
                    candidate,
                    conn=conn,
                    allowed_providers=allowed_providers,
                    timeout_seconds=timeout_seconds,
                    max_size_bytes=max_size_bytes,
                    use_head_first=use_head_first,
                    fallback_to_range_get=fallback_to_range_get,
                    user_agent=user_agent,
                    keep_429_as_retryable=keep_429_as_retryable,
                    mark_non_image=mark_non_image,
                    retry_only=retry_only,
                    force=force,
                    retry_enabled=retry_enabled,
                    retry_statuses=retry_statuses,
                    min_seconds_between_retries=min_seconds_between_retries,
                    max_retry_attempts=max_retry_attempts,
                    counts=counts,
                )

            rows = db.list_image_candidates(conn)
        finally:
            conn.close()

        self._export(rows)
        return {
            "status": "ok",
            "candidates_read": len(candidates),
            "checked": counts["checked"],
            "passed": counts["passed"],
            "blocked": counts["blocked"],
            "retryable": counts["retryable"],
            "failed": counts["failed"],
            "technical_rejected": counts["technical_rejected"],
            "skipped_by_max_retry_attempts": counts["skipped_by_max_retry_attempts"],
            "skipped_by_retry_window": counts["skipped_by_retry_window"],
            "skipped_by_status": counts["skipped_by_status"],
            "skipped_by_preflight_status": counts["skipped_by_preflight_status"],
            "skipped_by_missing_url": counts["skipped_by_missing_url"],
            "skipped_by_other_reason": counts["skipped_by_other_reason"],
            "skipped_by_not_selected_after_mark": counts["skipped_by_not_selected_after_mark"],
            "csv_path": str(self.output_csv_path),
        }

    def mark_for_retry(
        self,
        *,
        provider: str | None = None,
        image_id: str | None = None,
        limit: int | None = None,
        reason: str,
        preflight_status: str = "retryable",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Mark retryable candidates for operator-requested retry, without network calls."""
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("reason is required.")
        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            candidates = db.list_candidates_for_retry_mark(
                conn,
                provider=provider,
                image_id=image_id,
                preflight_statuses=(preflight_status,),
                limit=limit,
            )
            image_ids = [str(row["image_id"]) for row in candidates]
            marked = 0
            if not dry_run:
                marked = db.mark_candidates_retry_requested(
                    conn,
                    image_ids,
                    reason=clean_reason,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                )
            rows = db.list_image_candidates(conn)
        finally:
            conn.close()

        if not dry_run:
            self._export(rows)
        return {
            "status": "ok",
            "provider": provider,
            "candidates_matched": len(candidates),
            "marked": marked,
            "dry_run": dry_run,
            "image_ids": image_ids[:10],
            "csv_path": str(self.output_csv_path),
            "message": "" if candidates else "No hay candidatos retryable con esos filtros.",
        }

    def force_retry_now(
        self,
        *,
        provider: str | None = None,
        image_id: str | None = None,
        limit: int | None = None,
        reason: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Retry preflight now for retryable candidates, bypassing only time backoff."""
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("reason is required.")
        cfg = load_config().get("candidate_preflight", {})
        allowed_providers = {str(x) for x in cfg.get("allowed_providers", ["wikimedia"])}
        timeout_seconds = int(cfg.get("timeout_seconds", 15))
        max_size_bytes = int(cfg.get("max_file_size_mb", 8)) * 1024 * 1024
        use_head_first = bool(cfg.get("use_head_first", True))
        fallback_to_range_get = bool(cfg.get("fallback_to_range_get", True))
        user_agent = str(cfg.get("user_agent", "album_sticker_factory/0.1 local preflight tool"))
        mark_non_image = bool(cfg.get("mark_non_image_as_technical_rejected", True))
        keep_429_as_retryable = bool(cfg.get("keep_429_as_retryable", True))

        retry_cfg = load_config().get("preflight_retry", {})
        retry_enabled = bool(retry_cfg.get("enabled", True))
        retry_statuses = tuple(retry_cfg.get("statuses_to_retry", ["retryable"]))
        min_seconds_between_retries = int(retry_cfg.get("min_seconds_between_retries", 300))
        max_retry_attempts = int(retry_cfg.get("max_retry_attempts", 3))
        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            if image_id:
                candidate = db.get_image_candidate_by_id(conn, image_id)
                if not candidate:
                    return {
                        "status": "ok",
                        "provider": provider,
                        "candidates_matched": 0,
                        "forced_marked": 0,
                        "checked": 0,
                        "passed": 0,
                        "blocked": 0,
                        "retryable": 0,
                        "failed": 0,
                        "technical_rejected": 0,
                        "skipped_by_provider": 0,
                        "skipped_by_candidate_status": 0,
                        "skipped_by_preflight_status": 0,
                        "skipped_by_max_retry_attempts": 0,
                        "skipped_by_retry_window": 0,
                        "skipped_by_status": 0,
                        "skipped_by_missing_url": 0,
                        "skipped_by_other_reason": 1,
                        "skipped_by_not_selected_after_mark": 0,
                        "dry_run": dry_run,
                        "image_ids": [],
                        "csv_path": str(self.output_csv_path),
                        "message": f"image_id {image_id} no existe.",
                    }
                if provider and str(candidate.get("provider") or "") != provider:
                    return self._force_retry_skip_result(
                        provider=provider,
                        image_id=image_id,
                        reason="provider distinto",
                        skip_key="skipped_by_provider",
                        dry_run=dry_run,
                    )
                if str(candidate.get("status") or "") not in {"found", "needs_review", "approved"}:
                    return self._force_retry_skip_result(
                        provider=provider,
                        image_id=image_id,
                        reason="candidate status no elegible",
                        skip_key="skipped_by_candidate_status",
                        dry_run=dry_run,
                    )
                if str(candidate.get("preflight_status") or "") not in retry_statuses:
                    return self._force_retry_skip_result(
                        provider=provider,
                        image_id=image_id,
                        reason="preflight_status no retryable",
                        skip_key="skipped_by_preflight_status",
                        dry_run=dry_run,
                    )
                candidates = [candidate]
            else:
                candidates = db.list_candidates_for_retry_mark(
                    conn,
                    provider=provider,
                    preflight_statuses=retry_statuses,
                    limit=min(limit or retry_cfg.get("max_candidates_per_run", 20), int(retry_cfg.get("max_candidates_per_run", 20))),
                )

            image_ids = [str(row["image_id"]) for row in candidates]
            if not dry_run:
                db.mark_candidates_retry_forced(
                    conn,
                    image_ids,
                    reason=clean_reason,
                    forced_at=datetime.now(timezone.utc).isoformat(),
                )
            if dry_run:
                return {
                    "status": "ok",
                    "provider": provider,
                    "candidates_matched": len(candidates),
                    "checked": 0,
                    "passed": 0,
                    "blocked": 0,
                    "retryable": 0,
                    "failed": 0,
                    "technical_rejected": 0,
                    "skipped_by_provider": 0,
                    "skipped_by_candidate_status": 0,
                    "skipped_by_preflight_status": 0,
                    "skipped_by_max_retry_attempts": 0,
                    "skipped_by_retry_window": 0,
                    "skipped_by_status": 0,
                    "skipped_by_missing_url": 0,
                    "skipped_by_other_reason": 0,
                    "skipped_by_not_selected_after_mark": 0,
                    "forced_marked": 0,
                    "dry_run": True,
                    "image_ids": image_ids[:10],
                    "csv_path": str(self.output_csv_path),
                    "message": "" if candidates else "No hay candidatos retryable con esos filtros.",
                }

            totals = {
                "checked": 0,
                "passed": 0,
                "blocked": 0,
                "retryable": 0,
                "failed": 0,
                "technical_rejected": 0,
                "skipped_by_provider": 0,
                "skipped_by_candidate_status": 0,
                "skipped_by_preflight_status": 0,
                "skipped_by_max_retry_attempts": 0,
                "skipped_by_retry_window": 0,
                "skipped_by_status": 0,
                "skipped_by_missing_url": 0,
                "skipped_by_other_reason": 0,
                "skipped_by_not_selected_after_mark": 0,
            }
            for candidate in candidates:
                self._process_candidate(
                    candidate,
                    conn=conn,
                    allowed_providers=allowed_providers,
                    timeout_seconds=timeout_seconds,
                    max_size_bytes=max_size_bytes,
                    use_head_first=use_head_first,
                    fallback_to_range_get=fallback_to_range_get,
                    user_agent=user_agent,
                    keep_429_as_retryable=keep_429_as_retryable,
                    mark_non_image=mark_non_image,
                    retry_only=True,
                    force=True,
                    retry_enabled=retry_enabled,
                    retry_statuses=retry_statuses,
                    min_seconds_between_retries=min_seconds_between_retries,
                    max_retry_attempts=max_retry_attempts,
                    counts=totals,
                )

            reason_bits = []
            if totals["skipped_by_provider"]:
                reason_bits.append(f"provider={totals['skipped_by_provider']}")
            if totals["skipped_by_candidate_status"]:
                reason_bits.append(f"candidate_status={totals['skipped_by_candidate_status']}")
            if totals["skipped_by_preflight_status"]:
                reason_bits.append(f"preflight_status={totals['skipped_by_preflight_status']}")
            if totals["skipped_by_max_retry_attempts"]:
                reason_bits.append(f"max_retry_attempts={totals['skipped_by_max_retry_attempts']}")
            if totals["skipped_by_retry_window"]:
                reason_bits.append(f"retry_window={totals['skipped_by_retry_window']}")
            if totals["skipped_by_status"]:
                reason_bits.append(f"status={totals['skipped_by_status']}")
            if totals["skipped_by_missing_url"]:
                reason_bits.append(f"missing_url={totals['skipped_by_missing_url']}")
            if totals["skipped_by_other_reason"]:
                reason_bits.append(f"other={totals['skipped_by_other_reason']}")
            if totals["checked"] == 0 and candidates and not reason_bits:
                totals["skipped_by_not_selected_after_mark"] = len(candidates)
                reason_bits.append(f"not_selected_after_mark={len(candidates)}")

            return {
                "status": "ok",
                "provider": provider,
                "candidates_matched": len(candidates),
                "forced_marked": len(image_ids),
                "dry_run": False,
                "image_ids": image_ids[:10],
                "csv_path": str(self.output_csv_path),
                "message": "" if candidates else "No hay candidatos retryable con esos filtros.",
                "skip_summary": ", ".join(reason_bits),
                **totals,
            }
        finally:
            conn.close()

    def _force_retry_skip_result(
        self,
        *,
        provider: str | None,
        image_id: str,
        reason: str,
        skip_key: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": provider,
            "candidates_matched": 0,
            "forced_marked": 0,
            "checked": 0,
            "passed": 0,
            "blocked": 0,
            "retryable": 0,
            "failed": 0,
            "technical_rejected": 0,
            "skipped_by_provider": 0,
            "skipped_by_candidate_status": 0,
            "skipped_by_preflight_status": 0,
            "skipped_by_max_retry_attempts": 0,
            "skipped_by_retry_window": 0,
            "skipped_by_status": 0,
            "skipped_by_missing_url": 0,
            "skipped_by_other_reason": 0,
            "skipped_by_not_selected_after_mark": 0,
            skip_key: 1,
            "dry_run": dry_run,
            "image_ids": [image_id],
            "csv_path": str(self.output_csv_path),
            "message": f"image_id {image_id}: {reason}.",
        }

    def _process_candidate(
        self,
        candidate: dict[str, Any],
        *,
        conn,
        allowed_providers: set[str],
        timeout_seconds: int,
        max_size_bytes: int,
        use_head_first: bool,
        fallback_to_range_get: bool,
        user_agent: str,
        keep_429_as_retryable: bool,
        mark_non_image: bool,
        retry_only: bool,
        force: bool,
        retry_enabled: bool,
        retry_statuses: tuple[str, ...],
        min_seconds_between_retries: int,
        max_retry_attempts: int,
        counts: dict[str, int],
    ) -> None:
        if retry_only:
            if not retry_enabled:
                counts["skipped_by_other_reason"] += 1
                return
            if str(candidate.get("preflight_status") or "") not in retry_statuses:
                counts["skipped_by_preflight_status"] += 1
                return
            retry_count = int(candidate.get("preflight_retry_count") or 0)
            if retry_count >= max_retry_attempts:
                counts["skipped_by_max_retry_attempts"] += 1
                return
            if not force and candidate.get("preflight_checked_at"):
                last_checked = str(candidate.get("preflight_checked_at") or "")
                if last_checked:
                    try:
                        dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
                        delta = datetime.now(timezone.utc) - dt
                        if delta.total_seconds() < min_seconds_between_retries:
                            counts["skipped_by_retry_window"] += 1
                            return
                    except Exception:
                        counts["skipped_by_other_reason"] += 1
                        return

        counts["checked"] += 1
        result = self._check_candidate(
            candidate,
            allowed_providers=allowed_providers,
            timeout_seconds=timeout_seconds,
            max_size_bytes=max_size_bytes,
            use_head_first=use_head_first,
            fallback_to_range_get=fallback_to_range_get,
            user_agent=user_agent,
            keep_429_as_retryable=keep_429_as_retryable,
        )

        candidate_status = None
        decision_reason = candidate.get("decision_reason") or ""
        if result["preflight_status"] == "passed":
            counts["passed"] += 1
        elif result["preflight_status"] == "blocked":
            counts["blocked"] += 1
            if mark_non_image and result.get("block_reject", False):
                candidate_status = "technical_rejected"
                counts["technical_rejected"] += 1
                reason = str(result.get("preflight_error", "blocked"))
                decision_reason = f"{decision_reason};preflight_blocked:{reason}".strip(";")
        elif result["preflight_status"] == "retryable":
            counts["retryable"] += 1
        elif result["preflight_status"] == "failed":
            counts["failed"] += 1
        elif result["preflight_status"] == "skipped":
            counts["skipped_by_missing_url"] += 1

        db.update_candidate_preflight_result(
            conn,
            candidate["image_id"],
            preflight_status=result["preflight_status"],
            preflight_error=result.get("preflight_error", ""),
            preflight_content_type=result.get("preflight_content_type", ""),
            preflight_content_length=result.get("preflight_content_length"),
            preflight_checked_at=datetime.now(timezone.utc).isoformat(),
            preflight_retry_count=(
                int(candidate.get("preflight_retry_count") or 0) + 1 if retry_only else int(candidate.get("preflight_retry_count") or 0)
            ),
            preflight_last_retry_at=datetime.now(timezone.utc).isoformat() if retry_only else candidate.get("preflight_last_retry_at"),
            candidate_status=candidate_status,
            decision_reason=decision_reason if candidate_status else None,
        )

    def _check_candidate(
        self,
        candidate: dict[str, Any],
        *,
        allowed_providers: set[str],
        timeout_seconds: int,
        max_size_bytes: int,
        use_head_first: bool,
        fallback_to_range_get: bool,
        user_agent: str,
        keep_429_as_retryable: bool,
    ) -> dict[str, Any]:
        provider = str(candidate.get("provider") or "")
        if provider not in allowed_providers:
            return {"preflight_status": "blocked", "preflight_error": "provider_not_allowed", "block_reject": True}

        image_url = str(candidate.get("image_url") or "").strip()
        if not image_url:
            return {"preflight_status": "skipped", "preflight_error": "missing_image_url"}

        checks = []
        if use_head_first:
            checks.append(("HEAD", False))
        if fallback_to_range_get:
            checks.append(("GET", True))
        if not checks:
            checks.append(("GET", True))

        last_error = "failed"
        for method, ranged in checks:
            req = Request(image_url, method=method, headers={"User-Agent": user_agent})
            if ranged:
                req.add_header("Range", "bytes=0-0")
            try:
                with urlopen(req, timeout=timeout_seconds) as resp:
                    ctype = str(resp.headers.get("Content-Type", "")).split(";")[0].strip().lower()
                    clen_raw = str(resp.headers.get("Content-Length", "")).strip()
                    clen = int(clen_raw) if clen_raw.isdigit() else None
                    if ctype not in ALLOWED_RASTER_CONTENT_TYPES:
                        return {
                            "preflight_status": "blocked",
                            "preflight_error": f"unsupported_content_type:{ctype or 'unknown'}",
                            "preflight_content_type": ctype,
                            "preflight_content_length": clen,
                            "block_reject": True,
                        }
                    if clen is not None and clen > max_size_bytes:
                        return {
                            "preflight_status": "blocked",
                            "preflight_error": "file_too_large",
                            "preflight_content_type": ctype,
                            "preflight_content_length": clen,
                            "block_reject": True,
                        }
                    return {
                        "preflight_status": "passed",
                        "preflight_error": "",
                        "preflight_content_type": ctype,
                        "preflight_content_length": clen,
                    }
            except HTTPError as exc:
                code = int(getattr(exc, "code", 0))
                if code == 429 and keep_429_as_retryable:
                    return {"preflight_status": "retryable", "preflight_error": "http_error:429"}
                if method == "HEAD" and code in (403, 405):
                    last_error = f"http_error:{code}"
                    continue
                return {"preflight_status": "failed", "preflight_error": f"http_error:{code}"}
            except URLError as exc:
                detail = str(getattr(exc, "reason", "") or exc).splitlines()[0][:80]
                if "timed out" in detail.lower():
                    return {"preflight_status": "retryable", "preflight_error": f"url_error:{detail}"}
                last_error = f"url_error:{detail}"
            except Exception as exc:
                last_error = f"failed:{str(exc).splitlines()[0][:80]}"

        if last_error.startswith("url_error:"):
            return {"preflight_status": "failed", "preflight_error": last_error}
        return {"preflight_status": "failed", "preflight_error": last_error}

    def _export(self, rows: list[dict[str, Any]]) -> None:
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
