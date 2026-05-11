"""Crop downloaded images into square sticker candidates."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from core import db
from core.config import load_config
from core.paths import DB_PATH, ROOT_DIR, STICKERS_MANIFEST_CSV_PATH, STICKERS_DIR


class CropAgent:
    """Crop downloaded images into square sticker-ready candidates."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
        output_dir: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or STICKERS_MANIFEST_CSV_PATH)
        self.output_dir = Path(output_dir or STICKERS_DIR)

    def run(
        self,
        provider: str | None = None,
        limit: int | None = None,
        sticker_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        cfg = load_config().get("output", {})
        final_size = int(cfg.get("final_size_px", 800))
        format_name = str(cfg.get("format", "webp")).lower()
        if format_name not in {"webp", "jpg", "jpeg", "png"}:
            format_name = "webp"

        provider = None if provider in {None, "", "auto"} else provider
        effective_limit = limit if limit is not None else 10
        if effective_limit <= 0:
            raise ValueError("Crop limit must be positive.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            candidates = db.list_downloaded_candidates_for_crop(
                conn=conn,
                provider=provider,
                sticker_ids=sticker_ids,
                limit=effective_limit,
            )
            if sticker_ids:
                candidates = self._one_candidate_per_sticker(candidates)
            if not candidates:
                self._export_manifest([])
                return {
                    "status": "ok",
                    "downloaded_read": 0,
                    "cropped": 0,
                    "skipped": 0,
                    "csv_path": str(self.output_csv_path),
                    "output_dir": str(self.output_dir),
                    "message": "No hay candidatos descargados para recortar.",
                }

            rows: list[dict[str, Any]] = []
            cropped = 0
            skipped = 0
            for candidate in candidates:
                try:
                    row = self._crop_one(
                        candidate=candidate,
                        final_size=final_size,
                        format_name=format_name,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    skipped += 1
                    db.update_candidate_export_result(
                        conn,
                        candidate["image_id"],
                        status="downloaded",
                        exported_at=None,
                        cropped_path="",
                    )
                    continue
                if row is None:
                    skipped += 1
                    continue
                rows.append(row)
                cropped += 1
                sticker_id = str(candidate.get("sticker_id") or "unknown-sticker")
                db.update_candidate_export_result(
                    conn,
                    candidate["image_id"],
                    status="exported",
                    exported_at=datetime.now(timezone.utc).isoformat(),
                    cropped_path=row["sticker_path"],
                )
                db.update_sticker_status(conn, sticker_id, "exported")
            self._export_manifest(rows)
        finally:
            conn.close()

        return {
            "status": "ok",
            "downloaded_read": len(candidates),
            "cropped": cropped,
            "skipped": skipped,
            "csv_path": str(self.output_csv_path),
            "output_dir": str(self.output_dir),
        }

    def _crop_one(self, *, candidate: dict[str, Any], final_size: int, format_name: str) -> dict[str, Any] | None:
        local_path = str(candidate.get("local_path") or "").strip()
        if not local_path:
            return None
        input_path = Path(local_path)
        if not input_path.is_absolute():
            input_path = ROOT_DIR / local_path
        if not input_path.exists():
            return None

        sticker_id = str(candidate.get("sticker_id") or "unknown-sticker")
        image_id = str(candidate.get("image_id") or "unknown-image")
        provider = str(candidate.get("provider") or "")
        source_page = str(candidate.get("source_page") or "")
        image_url = str(candidate.get("image_url") or "")
        license_status = str(candidate.get("license_status") or "")
        metadata_score = candidate.get("metadata_score")
        relevance_score = candidate.get("relevance_score")

        with Image.open(input_path) as image:
            image = image.convert("RGB")
            size = min(image.width, image.height)
            left = (image.width - size) // 2
            top = (image.height - size) // 2
            cropped = image.crop((left, top, left + size, top + size))
            resized = cropped.resize((final_size, final_size), Image.Resampling.LANCZOS)

            self.output_dir.mkdir(parents=True, exist_ok=True)
            sticker_path = self.output_dir / f"{sticker_id}.webp"
            resized.save(sticker_path, "WEBP")

        return {
            "sticker_id": sticker_id,
            "image_id": image_id,
            "provider": provider,
            "source_page": source_page,
            "image_url": image_url,
            "local_path": str(input_path).replace("\\", "/"),
            "sticker_path": str(sticker_path).replace("\\", "/"),
            "license_status": license_status,
            "metadata_score": metadata_score,
            "relevance_score": relevance_score,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _export_manifest(self, rows: list[dict[str, Any]]) -> None:
        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "sticker_id",
            "image_id",
            "provider",
            "source_page",
            "image_url",
            "local_path",
            "sticker_path",
            "license_status",
            "metadata_score",
            "relevance_score",
            "generated_at",
        ]
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _one_candidate_per_sticker(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            sticker_id = str(candidate.get("sticker_id") or "")
            if not sticker_id:
                continue
            current = best.get(sticker_id)
            score = float(candidate.get("relevance_score") or 0.0)
            current_score = float(current.get("relevance_score") or 0.0) if current else -1.0
            if current is None or score > current_score or (
                score == current_score and str(candidate.get("image_id") or "") < str(current.get("image_id") or "")
            ):
                best[sticker_id] = candidate
        return list(best.values())
