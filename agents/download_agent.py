"""Download approved image candidates to local raw storage."""

from __future__ import annotations

import csv
import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core import db
from core.config import load_config
from core.paths import DB_PATH, IMAGE_CANDIDATES_CSV_PATH, ROOT_DIR

MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class DownloadAgent:
    """Download agent with strict approved-only policy."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or IMAGE_CANDIDATES_CSV_PATH)

    def run(self, provider: str | None = None, limit: int | None = None) -> dict[str, Any]:
        cfg = load_config().get("download", {})
        if not bool(cfg.get("enabled", True)):
            raise ValueError("download.enabled is false.")
        if not bool(cfg.get("approved_only", True)):
            raise ValueError("Prompt 10 requires download.approved_only=true for safety.")

        output_dir = self._resolve_output_dir(str(cfg.get("output_dir", "output/raw")))
        max_per_run = int(cfg.get("max_candidates_per_run", 10))
        timeout_seconds = int(cfg.get("timeout_seconds", 20))
        max_file_size_mb = int(cfg.get("max_file_size_mb", 8))
        max_file_size_bytes = max_file_size_mb * 1024 * 1024
        allowed_providers = {str(p) for p in cfg.get("allowed_providers", ["wikimedia"])}
        allowed_extensions = {str(e).lower() for e in cfg.get("allowed_extensions", [".jpg", ".jpeg", ".png", ".webp"])}
        allowed_mime_prefixes = tuple(str(p) for p in cfg.get("allowed_mime_prefixes", ["image/"]))
        user_agent = str(cfg.get("user_agent", "album_sticker_factory/0.1 local download tool"))

        effective_limit = limit if limit is not None else max_per_run
        effective_limit = min(effective_limit, max_per_run)
        if effective_limit <= 0:
            raise ValueError("Download limit must be positive.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            approved_total = db.count_rows(conn, "image_candidates")
            candidates = db.list_approved_candidates_for_download(
                conn=conn,
                provider=provider,
                limit=effective_limit,
            )
            if not candidates:
                exported_rows = db.list_image_candidates(conn)
                self._export_candidates_csv(exported_rows)
                return {
                    "status": "ok",
                    "approved_read": 0,
                    "download_attempted": 0,
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 0,
                    "csv_path": str(self.output_csv_path),
                    "output_dir": str(output_dir),
                    "message": (
                        "No hay candidatos approved para descargar. "
                        "Edita data/review_decisions.csv y ejecuta apply-reviews."
                    ),
                }

            counts = {"attempted": 0, "downloaded": 0, "skipped": 0, "failed": 0}
            for candidate in candidates:
                counts["attempted"] += 1
                result = self._download_one(
                    candidate=candidate,
                    output_dir=output_dir,
                    timeout_seconds=timeout_seconds,
                    max_file_size_bytes=max_file_size_bytes,
                    allowed_providers=allowed_providers,
                    allowed_extensions=allowed_extensions,
                    allowed_mime_prefixes=allowed_mime_prefixes,
                    user_agent=user_agent,
                )
                if result["action"] == "downloaded":
                    counts["downloaded"] += 1
                    db.update_candidate_download_result(
                        conn,
                        candidate["image_id"],
                        local_path=result["local_path"],
                        file_sha256=result["file_sha256"],
                        file_size_bytes=result["file_size_bytes"],
                        downloaded_at=result["downloaded_at"],
                        download_error="",
                        status="downloaded",
                    )
                elif result["action"] == "skipped":
                    counts["skipped"] += 1
                    if result.get("download_error"):
                        db.update_candidate_download_result(
                            conn,
                            candidate["image_id"],
                            download_error=result["download_error"],
                        )
                else:
                    counts["failed"] += 1
                    db.update_candidate_download_result(
                        conn,
                        candidate["image_id"],
                        download_error=result.get("download_error", "provider_exception:unknown"),
                    )

            exported_rows = db.list_image_candidates(conn)
        finally:
            conn.close()

        self._export_candidates_csv(exported_rows)
        return {
            "status": "ok",
            "approved_read": len(candidates),
            "download_attempted": counts["attempted"],
            "downloaded": counts["downloaded"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "csv_path": str(self.output_csv_path),
            "output_dir": str(output_dir),
        }

    def _download_one(
        self,
        *,
        candidate: dict[str, Any],
        output_dir: Path,
        timeout_seconds: int,
        max_file_size_bytes: int,
        allowed_providers: set[str],
        allowed_extensions: set[str],
        allowed_mime_prefixes: tuple[str, ...],
        user_agent: str,
    ) -> dict[str, Any]:
        image_id = str(candidate["image_id"])
        status = str(candidate.get("status", ""))
        if status != "approved":
            return {"action": "failed", "download_error": "not_approved"}
        preflight_status = str(candidate.get("preflight_status") or "").strip().lower()
        preflight_error = str(candidate.get("preflight_error") or "").strip()
        if preflight_status == "blocked":
            detail = preflight_error or "blocked"
            return {"action": "skipped", "download_error": f"preflight_blocked:{detail}"}
        if preflight_status == "retryable":
            return {"action": "skipped", "download_error": "preflight_retryable"}
        preflight_content_type = str(candidate.get("preflight_content_type") or "").strip().lower()
        if preflight_content_type and not preflight_content_type.startswith("image/"):
            return {"action": "skipped", "download_error": f"preflight_blocked:invalid_content_type:{preflight_content_type}"}
        provider = str(candidate.get("provider", ""))
        if provider not in allowed_providers:
            return {"action": "skipped", "download_error": "provider_not_allowed"}

        image_url = str(candidate.get("image_url") or "").strip()
        if not image_url:
            return {"action": "failed", "download_error": "missing_image_url"}

        chapter_slug = str(candidate.get("chapter_slug") or "unknown-chapter")
        sticker_id = str(candidate.get("sticker_id") or "unknown-sticker")
        candidate_dir = output_dir / chapter_slug / sticker_id
        candidate_dir.mkdir(parents=True, exist_ok=True)

        existing_local = str(candidate.get("local_path") or "").strip()
        if existing_local:
            existing_abs = Path(existing_local)
            if not existing_abs.is_absolute():
                existing_abs = ROOT_DIR / existing_local
            if existing_abs.exists():
                return {"action": "skipped"}

        request = Request(image_url, headers={"User-Agent": user_agent})
        try:
            with urlopen(request, timeout=timeout_seconds) as resp:
                status_code = int(getattr(resp, "status", 200))
                if status_code != 200:
                    return {"action": "failed", "download_error": f"http_error:{status_code}"}
                content_type = str(resp.headers.get("Content-Type", "")).split(";")[0].strip().lower()
                if not content_type.startswith(allowed_mime_prefixes):
                    return {
                        "action": "failed",
                        "download_error": f"invalid_content_type:{content_type or 'unknown'}",
                    }
                ext = self._pick_extension(
                    image_url=image_url,
                    content_type=content_type,
                    allowed_extensions=allowed_extensions,
                )
                file_path = candidate_dir / f"{image_id}{ext}"
                buffer = bytearray()
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if len(buffer) > max_file_size_bytes:
                        return {"action": "failed", "download_error": "file_too_large"}
        except HTTPError as exc:
            return {"action": "failed", "download_error": f"http_error:{exc.code}"}
        except URLError as exc:
            detail = str(getattr(exc, "reason", "") or exc).splitlines()[0][:80]
            return {"action": "failed", "download_error": f"url_error:{detail}"}
        except Exception as exc:
            detail = str(exc).splitlines()[0][:80]
            return {"action": "failed", "download_error": f"provider_exception:{detail}"}

        file_sha256 = hashlib.sha256(buffer).hexdigest()
        file_size = len(buffer)

        # Idempotency if target already exists with same content.
        if file_path.exists():
            try:
                existing = file_path.read_bytes()
                existing_sha = hashlib.sha256(existing).hexdigest()
                if existing_sha == file_sha256:
                    rel_path = self._storage_path(file_path)
                    return {
                        "action": "skipped",
                        "local_path": rel_path,
                        "file_sha256": file_sha256,
                        "file_size_bytes": file_size,
                    }
            except Exception:
                pass

        try:
            file_path.write_bytes(buffer)
        except Exception as exc:
            detail = str(exc).splitlines()[0][:80]
            return {"action": "failed", "download_error": f"write_error:{detail}"}

        rel_path = self._storage_path(file_path)
        return {
            "action": "downloaded",
            "local_path": rel_path,
            "file_sha256": file_sha256,
            "file_size_bytes": file_size,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
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
    def _pick_extension(image_url: str, content_type: str, allowed_extensions: set[str]) -> str:
        ext = MIME_TO_EXT.get(content_type, "")
        if not ext:
            parsed = urlparse(image_url)
            ext = Path(parsed.path).suffix.lower()
            if ext == ".jpeg":
                ext = ".jpg"
        if not ext:
            guess, _ = mimetypes.guess_type(image_url)
            if guess:
                ext = MIME_TO_EXT.get(guess, "")
        if not ext:
            ext = ".jpg"
        if ext not in allowed_extensions:
            return ".jpg"
        return ext

    @staticmethod
    def _resolve_output_dir(output_dir_cfg: str) -> Path:
        path = Path(output_dir_cfg)
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    @staticmethod
    def _storage_path(file_path: Path) -> str:
        resolved = file_path.resolve()
        try:
            rel = resolved.relative_to(ROOT_DIR.resolve())
            return str(rel).replace("\\", "/")
        except ValueError:
            return str(resolved).replace("\\", "/")
