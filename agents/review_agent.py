"""Manual review agent for needs_review candidates."""

from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import db
from core.config import load_config
from core.paths import DB_PATH, REVIEW_DECISIONS_CSV_PATH, REVIEW_REPORT_HTML_PATH, ROOT_DIR

DECISION_HEADERS = [
    "image_id",
    "review_status",
    "notes",
    "preflight_status",
    "preflight_error",
    "preflight_content_type",
    "metadata_score",
    "relevance_score",
    "license_status",
    "source_page",
    "image_url",
]
ALLOWED_REVIEW_STATUS = {"approved", "rejected", "needs_more_info", "force_approved", ""}


class ReviewAgent:
    """Generate review materials and apply manual review decisions."""

    def __init__(
        self,
        db_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)

    def run(self, payload: dict | None = None) -> dict[str, Any]:
        payload = payload or {}
        action = str(payload.get("action", "review-candidates"))
        provider = payload.get("provider")
        limit = payload.get("limit")
        if action == "review-candidates":
            return self.review_candidates(provider=provider, limit=limit)
        if action == "apply-reviews":
            return self.apply_reviews()
        return {"status": "error", "message": f"Unsupported review action: {action}"}

    def review_candidates(self, provider: str | None = None, limit: int | None = None) -> dict[str, Any]:
        cfg = load_config().get("review", {})
        report_path = self._resolve_path(cfg.get("html_report_path"), REVIEW_REPORT_HTML_PATH)
        decisions_path = self._resolve_path(cfg.get("decisions_csv_path"), REVIEW_DECISIONS_CSV_PATH)
        allow_remote_preview = bool(cfg.get("allow_remote_image_preview", True))

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            candidates = db.list_image_candidates_by_status(
                conn=conn,
                statuses=("needs_review",),
                provider=provider,
                limit=limit,
            )
            all_candidates = {str(row["image_id"]): row for row in db.list_image_candidates(conn)}
            canonical_map = self._canonical_representatives(all_candidates.values())
        finally:
            conn.close()

        existing = self._load_decisions(decisions_path)
        existing_ids = set(existing.keys())
        added = 0
        unique_candidates = []
        for candidate in candidates:
            key = self._canonical_key(candidate)
            rep = canonical_map.get(key)
            if rep and str(rep["image_id"]) != str(candidate["image_id"]):
                continue
            unique_candidates.append(candidate)
        for candidate in unique_candidates:
            image_id = str(candidate["image_id"])
            prev = existing.get(image_id, {})
            if image_id not in existing:
                added += 1
            existing[image_id] = {
                "image_id": image_id,
                "review_status": str(prev.get("review_status", "")).strip(),
                "notes": str(prev.get("notes", "")).strip(),
                "preflight_status": str(candidate.get("preflight_status", "")),
                "preflight_error": str(candidate.get("preflight_error", "")),
                "preflight_content_type": str(candidate.get("preflight_content_type", "")),
                "metadata_score": str(candidate.get("metadata_score", "")),
                "relevance_score": str(candidate.get("relevance_score", "")),
                "license_status": str(candidate.get("license_status", "")),
                "source_page": str(candidate.get("source_page", "")),
                "image_url": str(candidate.get("image_url", "")),
            }
        # Preserve rows that are no longer in needs_review and refresh informative columns if candidate exists.
        for image_id, prev in list(existing.items()):
            if image_id in {str(c["image_id"]) for c in candidates}:
                continue
            src = all_candidates.get(image_id, {})
            if src:
                prev["preflight_status"] = str(src.get("preflight_status", ""))
                prev["preflight_error"] = str(src.get("preflight_error", ""))
                prev["preflight_content_type"] = str(src.get("preflight_content_type", ""))
                prev["metadata_score"] = str(src.get("metadata_score", ""))
                prev["relevance_score"] = str(src.get("relevance_score", ""))
                prev["license_status"] = str(src.get("license_status", ""))
                prev["source_page"] = str(src.get("source_page", ""))
                prev["image_url"] = str(src.get("image_url", ""))
                prev.setdefault("notes", str(prev.get("notes", "")).strip())
            for key in DECISION_HEADERS:
                prev.setdefault(key, "")
        self._write_decisions(decisions_path, existing)
        self._write_html_report(report_path, unique_candidates, allow_remote_preview=allow_remote_preview)

        return {
            "status": "ok",
            "candidates_needs_review": len(unique_candidates),
            "html_path": str(report_path),
            "decisions_csv_path": str(decisions_path),
            "decisions_existing": len(existing_ids),
            "decisions_added": added,
        }

    def apply_reviews(self) -> dict[str, Any]:
        cfg = load_config().get("review", {})
        safety_cfg = load_config().get("review_safety", {})
        block_if_blocked = bool(safety_cfg.get("block_approval_if_preflight_blocked", True))
        block_if_retryable = bool(safety_cfg.get("block_approval_if_preflight_retryable", True))
        block_if_missing = bool(safety_cfg.get("block_approval_if_preflight_missing", False))
        allow_override = bool(safety_cfg.get("allow_override_column", True))
        override_value = str(safety_cfg.get("override_value", "force_approved"))
        require_override_note = bool(safety_cfg.get("require_override_note", True))
        decisions_path = self._resolve_path(cfg.get("decisions_csv_path"), REVIEW_DECISIONS_CSV_PATH)
        reviewer = str(cfg.get("default_reviewer", "local_user"))
        rows = self._read_decisions_rows(decisions_path)
        if rows is None:
            return {
                "status": "ok",
                "rows_read": 0,
                "approved_applied": 0,
                "rejected_applied": 0,
                "needs_more_info_applied": 0,
                "unchanged": 0,
                "invalid_rows": 0,
                "message": "No existe data/review_decisions.csv. Ejecuta primero python main.py review-candidates",
            }

        reviews_payload: list[dict[str, Any]] = []
        candidate_status_updates: dict[str, str] = {}
        counts = {
            "approved_applied": 0,
            "rejected_applied": 0,
            "needs_more_info_applied": 0,
                "unchanged": 0,
                "invalid_rows": 0,
                "blocked_by_safety": 0,
                "force_approved_applied": 0,
        }
        preflight_by_image = self._get_preflight_map()
        reviewed_at = datetime.now(timezone.utc).isoformat()
        for row in rows:
            image_id = str(row.get("image_id", "")).strip()
            review_status = str(row.get("review_status", "")).strip()
            notes = str(row.get("notes", "")).strip()
            if not image_id:
                counts["invalid_rows"] += 1
                continue
            if review_status not in ALLOWED_REVIEW_STATUS:
                counts["invalid_rows"] += 1
                continue
            if review_status == "":
                counts["unchanged"] += 1
                continue

            pf = preflight_by_image.get(image_id, {})
            pf_status = str(pf.get("preflight_status", "")).strip().lower()
            pf_error = str(pf.get("preflight_error", "")).strip().lower()
            pf_ct = str(pf.get("preflight_content_type", "")).strip().lower()

            def block(reason: str) -> None:
                counts["blocked_by_safety"] += 1
                candidate_status_updates[image_id] = "needs_review"
                reviews_payload.append(
                    {
                        "review_id": f"REV-{image_id}",
                        "image_id": image_id,
                        "review_status": "needs_more_info",
                        "notes": f"{notes_text};{reason}",
                        "reviewed_at": reviewed_at,
                    }
                )

            review_id = f"REV-{image_id}"
            notes_text = notes if notes else f"reviewer={reviewer}"

            if review_status == "approved":
                if block_if_blocked and pf_status == "blocked":
                    block("approval_blocked_by_preflight_blocked")
                    continue
                if block_if_retryable and pf_status == "retryable":
                    block("approval_blocked_by_preflight_retryable")
                    continue
                if block_if_missing and not pf_status:
                    block("approval_blocked_by_missing_preflight")
                    continue
                candidate_status_updates[image_id] = "approved"
                counts["approved_applied"] += 1
                final_review_status = "approved"
            elif review_status == override_value:
                if not allow_override:
                    block("force_approved_not_allowed")
                    continue
                if require_override_note and not notes:
                    block("force_approved_requires_note")
                    continue
                if pf_ct in {"application/pdf", "text/html"}:
                    block("force_approved_blocked_by_content_type")
                    continue
                if pf_status == "blocked" and ("invalid_content_type" in pf_error or "non_image" in pf_error):
                    block("force_approved_blocked_by_non_image")
                    continue
                candidate_status_updates[image_id] = "approved"
                counts["force_approved_applied"] += 1
                final_review_status = override_value
            elif review_status == "rejected":
                candidate_status_updates[image_id] = "rejected"
                counts["rejected_applied"] += 1
                final_review_status = "rejected"
            elif review_status == "needs_more_info":
                candidate_status_updates[image_id] = "needs_review"
                counts["needs_more_info_applied"] += 1
                final_review_status = "needs_more_info"
            else:
                counts["invalid_rows"] += 1
                continue

            reviews_payload.append(
                {
                    "review_id": review_id,
                    "image_id": image_id,
                    "review_status": final_review_status,
                    "notes": notes_text,
                    "reviewed_at": reviewed_at,
                }
            )

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            db.upsert_reviews(conn, reviews_payload)
            db.update_candidate_statuses(conn, candidate_status_updates)
            review_status_counts = db.get_reviews_by_status(conn)
        finally:
            conn.close()

        return {
            "status": "ok",
            "rows_read": len(rows),
            **counts,
            "reviews_upserted": len(reviews_payload),
            "review_status_counts": review_status_counts,
        }

    def _load_decisions(self, path: Path) -> dict[str, dict[str, str]]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            loaded: dict[str, dict[str, str]] = {}
            for row in reader:
                image_id = str(row.get("image_id", "")).strip()
                if not image_id:
                    continue
                loaded[image_id] = {
                    "image_id": image_id,
                    "review_status": str(row.get("review_status", "")).strip(),
                    "notes": str(row.get("notes", "")).strip(),
                    "preflight_status": str(row.get("preflight_status", "")).strip(),
                    "preflight_error": str(row.get("preflight_error", "")).strip(),
                    "preflight_content_type": str(row.get("preflight_content_type", "")).strip(),
                    "metadata_score": str(row.get("metadata_score", "")).strip(),
                    "relevance_score": str(row.get("relevance_score", "")).strip(),
                    "license_status": str(row.get("license_status", "")).strip(),
                    "source_page": str(row.get("source_page", "")).strip(),
                    "image_url": str(row.get("image_url", "")).strip(),
                }
            return loaded

    def _read_decisions_rows(self, path: Path) -> list[dict[str, str]] | None:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def _write_decisions(self, path: Path, rows_by_image_id: dict[str, dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = [rows_by_image_id[key] for key in sorted(rows_by_image_id.keys())]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=DECISION_HEADERS)
            writer.writeheader()
            writer.writerows(ordered)

    def _write_html_report(
        self,
        path: Path,
        candidates: list[dict[str, Any]],
        allow_remote_preview: bool,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        cards = "\n".join(self._candidate_card(candidate, allow_remote_preview) for candidate in candidates)
        doc = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Review Candidates</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f6f7f9; color: #111; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }}
    .card {{ background: #fff; border: 1px solid #d7dbe0; border-radius: 6px; padding: 12px; }}
    .card.blocked {{ border-color: #c0392b; }}
    .card.retryable {{ border-color: #b8860b; }}
    .preview {{ width: 100%; max-height: 260px; object-fit: contain; background: #f2f3f5; border-radius: 4px; border: 1px solid #e3e6ea; }}
    .kv {{ margin-top: 8px; font-size: 13px; line-height: 1.45; }}
    .kv div {{ margin-bottom: 2px; }}
    .muted {{ color: #5b6470; font-size: 13px; }}
    code {{ background: #eef1f5; padding: 1px 4px; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>Review Manual de Candidatos</h1>
  <p class="muted">Para aprobar/rechazar, editar <code>data/review_decisions.csv</code> y luego ejecutar <code>python main.py apply-reviews</code>.</p>
  <p class="muted">No se descargan imagenes en este paso. Solo vista remota por URL.</p>
  <p><strong>Total needs_review:</strong> {len(candidates)}</p>
  <div class="grid">
    {cards}
  </div>
</body>
</html>
"""
        path.write_text(doc, encoding="utf-8")

    def _candidate_card(self, candidate: dict[str, Any], allow_remote_preview: bool) -> str:
        image_url = str(candidate.get("image_url") or "")
        source_page = str(candidate.get("source_page") or "")
        preflight_status = str(candidate.get("preflight_status") or "preflight no ejecutado")
        preflight_error = str(candidate.get("preflight_error") or "")
        preflight_type = str(candidate.get("preflight_content_type") or "")
        preflight_len = str(candidate.get("preflight_content_length") or "")
        retry_requested_at = str(candidate.get("retry_requested_at") or "")
        retry_requested_reason = str(candidate.get("retry_requested_reason") or "")
        retry_forced_at = str(candidate.get("retry_forced_at") or "")
        retry_forced_reason = str(candidate.get("retry_forced_reason") or "")
        last_retry_mode = str(candidate.get("last_retry_mode") or "")
        cls = "card"
        if preflight_status == "blocked":
            cls = "card blocked"
        elif preflight_status == "retryable":
            cls = "card retryable"
        recommendation = "Preflight pendiente"
        if preflight_status == "passed":
            recommendation = "OK para revision"
        elif preflight_status == "blocked":
            recommendation = "No aprobar: preflight bloqueado"
        elif preflight_status == "retryable":
            recommendation = "Reintentar preflight antes de aprobar"
        preview = (
            f'<img class="preview" src="{html.escape(image_url)}" alt="{html.escape(candidate["image_id"])}">'
            if allow_remote_preview and image_url
            else '<div class="preview"></div>'
        )
        return f"""
<article class="{cls}">
  {preview}
  <div class="kv">
    <div><strong>image_id:</strong> {html.escape(str(candidate.get("image_id", "")))}</div>
    <div><strong>sticker_id:</strong> {html.escape(str(candidate.get("sticker_id", "")))}</div>
    <div><strong>query_id:</strong> {html.escape(str(candidate.get("query_id", "")))}</div>
    <div><strong>provider:</strong> {html.escape(str(candidate.get("provider", "")))}</div>
    <div><strong>source_page:</strong> <a href="{html.escape(source_page)}" target="_blank" rel="noopener noreferrer">link</a></div>
    <div><strong>image_url:</strong> <a href="{html.escape(image_url)}" target="_blank" rel="noopener noreferrer">link</a></div>
    <div><strong>executed_query:</strong> {html.escape(str(candidate.get("executed_query", "")))}</div>
    <div><strong>width x height:</strong> {html.escape(str(candidate.get("width", "")))} x {html.escape(str(candidate.get("height", "")))}</div>
    <div><strong>relevance_score:</strong> {html.escape(str(candidate.get("relevance_score", "")))}</div>
    <div><strong>license_status:</strong> {html.escape(str(candidate.get("license_status", "")))}</div>
    <div><strong>metadata_score:</strong> {html.escape(str(candidate.get("metadata_score", "")))}</div>
    <div><strong>decision_reason:</strong> {html.escape(str(candidate.get("decision_reason", "")))}</div>
    <div><strong>preflight_status:</strong> {html.escape(preflight_status)}</div>
    <div><strong>preflight_error:</strong> {html.escape(preflight_error)}</div>
    <div><strong>preflight_content_type:</strong> {html.escape(preflight_type)}</div>
    <div><strong>preflight_content_length:</strong> {html.escape(preflight_len)}</div>
    <div><strong>retry_requested_at:</strong> {html.escape(retry_requested_at)}</div>
    <div><strong>retry_requested_reason:</strong> {html.escape(retry_requested_reason)}</div>
    <div><strong>retry_forced_at:</strong> {html.escape(retry_forced_at)}</div>
    <div><strong>retry_forced_reason:</strong> {html.escape(retry_forced_reason)}</div>
    <div><strong>last_retry_mode:</strong> {html.escape(last_retry_mode)}</div>
    <div><strong>recommendation:</strong> {html.escape(recommendation)}</div>
    <div class="muted"><strong>Decision:</strong> editar CSV con approved / rejected / needs_more_info</div>
    <div class="muted"><strong>Tip:</strong> blocked no deberia aprobarse; retryable puede reintentarse luego.</div>
  </div>
</article>
"""

    def _canonical_representatives(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = self._canonical_key(row)
            grouped.setdefault(key, []).append(row)

        reps: dict[str, dict[str, Any]] = {}
        for key, items in grouped.items():
            reps[key] = sorted(
                items,
                key=lambda row: (
                    0 if str(row.get("preflight_status") or "") == "passed" else 1,
                    0 if str(row.get("status") or "") == "needs_review" else 1,
                    -float(row.get("metadata_score") or 0.0),
                    -float(row.get("relevance_score") or 0.0),
                    str(row.get("image_id") or ""),
                ),
            )[0]
        return reps

    @staticmethod
    def _canonical_key(row: dict[str, Any]) -> str:
        return db.canonical_media_key(
            str(row.get("provider") or ""),
            str(row.get("image_url") or ""),
            str(row.get("source_page") or ""),
        )

    def _get_preflight_map(self) -> dict[str, dict[str, Any]]:
        conn = db.get_connection(self.db_path)
        try:
            rows = db.list_image_candidates(conn)
        finally:
            conn.close()
        return {str(row["image_id"]): row for row in rows}

    @staticmethod
    def _resolve_path(value: Any, default_path: Path) -> Path:
        if not value:
            return default_path
        raw = Path(str(value))
        if raw.is_absolute():
            return raw
        return ROOT_DIR / raw
