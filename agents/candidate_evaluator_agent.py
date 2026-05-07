"""Metadata-only candidate evaluator (no downloads)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import db
from core.config import load_config
from core.paths import DB_PATH, IMAGE_CANDIDATES_CSV_PATH


class CandidateEvaluatorAgent:
    """Evaluate image candidates with existing metadata and set review/rejection states."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or IMAGE_CANDIDATES_CSV_PATH)

    def run(self, provider: str | None = None, limit: int | None = None) -> dict[str, Any]:
        config = load_config()
        eval_cfg = config.get("candidate_evaluation", {})
        if not bool(eval_cfg.get("enabled", True)):
            raise ValueError("candidate_evaluation.enabled is false.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            total_candidates = db.count_rows(conn, "image_candidates")
            if total_candidates == 0:
                return {
                    "status": "ok",
                    "candidates_read": 0,
                    "candidates_evaluated": 0,
                    "needs_review": 0,
                    "technical_rejected": 0,
                    "semantic_rejected": 0,
                    "kept_found": 0,
                    "csv_path": str(self.output_csv_path),
                    "message": "No hay candidatos para evaluar. Ejecuta primero execute-routes.",
                }

            candidates = db.list_image_candidates_for_evaluation(
                conn=conn,
                provider=provider,
                limit=limit,
            )
            updates: list[dict[str, Any]] = []
            counts = {
                "needs_review": 0,
                "technical_rejected": 0,
                "semantic_rejected": 0,
                "found": 0,
            }
            evaluated_at = datetime.now(timezone.utc).isoformat()

            for candidate in candidates:
                evaluation = self._evaluate_candidate(candidate=candidate, cfg=eval_cfg)
                updates.append(
                    {
                        "image_id": candidate["image_id"],
                        "status": evaluation["status"],
                        "metadata_score": evaluation["metadata_score"],
                        "decision_reason": evaluation["decision_reason"],
                        "evaluated_at": evaluated_at,
                    }
                )
                counts[evaluation["status"]] = counts.get(evaluation["status"], 0) + 1

            db.update_image_candidate_evaluations(conn, updates)
            exported_rows = db.list_image_candidates(conn)
        finally:
            conn.close()

        self._export_candidates_csv(exported_rows)
        return {
            "status": "ok",
            "candidates_read": len(candidates),
            "candidates_evaluated": len(updates),
            "needs_review": counts.get("needs_review", 0),
            "technical_rejected": counts.get("technical_rejected", 0),
            "semantic_rejected": counts.get("semantic_rejected", 0),
            "kept_found": counts.get("found", 0),
            "csv_path": str(self.output_csv_path),
        }

    def _evaluate_candidate(self, candidate: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        min_width = int(cfg.get("min_width", 400))
        min_height = int(cfg.get("min_height", 400))
        preferred_min_width = int(cfg.get("preferred_min_width", 800))
        preferred_min_height = int(cfg.get("preferred_min_height", 800))
        min_relevance = float(cfg.get("min_relevance_score", 0.15))
        require_image_url = bool(cfg.get("require_image_url", True))
        reject_missing_dimensions = bool(cfg.get("reject_missing_dimensions", False))
        unknown_license_allowed_for_review = bool(cfg.get("unknown_license_allowed_for_review", True))

        image_url = str(candidate.get("image_url") or "").strip()
        source_page = str(candidate.get("source_page") or "").strip()
        license_status = str(candidate.get("license_status") or "unknown").strip().lower()
        width = self._to_int(candidate.get("width"))
        height = self._to_int(candidate.get("height"))
        relevance_score = self._to_float(candidate.get("relevance_score"))
        preflight_content_type = str(candidate.get("preflight_content_type") or "").strip().lower()
        preflight_status = str(candidate.get("preflight_status") or "").strip().lower()

        reasons: list[str] = []

        if require_image_url and not image_url:
            return self._result("technical_rejected", 0.0, "missing_image_url")
        if preflight_content_type and not preflight_content_type.startswith("image/"):
            return self._result("technical_rejected", 0.0, "preflight_non_image")
        if preflight_status == "blocked":
            return self._result("technical_rejected", 0.0, "preflight_blocked")

        if license_status == "restricted":
            return self._result("technical_rejected", 0.0, "restricted_license")

        if width is not None and height is not None:
            if width < min_width or height < min_height:
                return self._result(
                    "technical_rejected",
                    0.0,
                    f"low_resolution:{width}x{height}",
                )
        elif reject_missing_dimensions:
            return self._result("technical_rejected", 0.0, "missing_dimensions")

        if relevance_score is not None and relevance_score < min_relevance:
            return self._result(
                "semantic_rejected",
                0.0,
                f"low_relevance:{relevance_score:.4f}",
            )

        # Deterministic metadata score in [0, 1].
        score = 0.0
        if image_url:
            score += 0.20
            reasons.append("has_image_url")
        if preflight_status == "passed":
            score += 0.05
            reasons.append("preflight_passed")
        if source_page:
            score += 0.10
            reasons.append("has_source_page")
        if width is not None and height is not None and width >= min_width and height >= min_height:
            score += 0.20
            reasons.append("meets_min_dimensions")
            if width >= preferred_min_width and height >= preferred_min_height:
                score += 0.15
                reasons.append("meets_preferred_dimensions")
        elif width is None or height is None:
            reasons.append("dimensions_missing_allowed")

        if relevance_score is not None:
            score += min(0.25, max(0.0, relevance_score) * 0.25)
            reasons.append(f"relevance:{relevance_score:.4f}")
        else:
            reasons.append("relevance_missing")

        if license_status in {"clear", "attribution_required"}:
            score += 0.10
            reasons.append(f"license:{license_status}")
        elif license_status in {"unknown", "needs_manual_review"} and unknown_license_allowed_for_review:
            score += 0.03
            reasons.append(f"license:{license_status}")
        else:
            reasons.append(f"license:{license_status}")

        score = round(min(1.0, max(0.0, score)), 4)
        return self._result("needs_review", score, ";".join(reasons))

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
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _result(status: str, metadata_score: float, reason: str) -> dict[str, Any]:
        return {
            "status": status,
            "metadata_score": round(float(metadata_score), 4),
            "decision_reason": reason,
        }
