"""Manual URL provider for locally curated raster image URLs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_RASTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ManualUrlsProvider:
    """Load candidates from a CSV of manually curated image URLs."""

    name = "manual_urls"
    enabled = True

    def run(self, payload: dict | None = None) -> dict[str, Any]:
        payload = payload or {}
        csv_path = Path(payload.get("csv_path", "data/manual_image_urls.csv"))
        rows = self._read_rows(csv_path)
        candidates: list[dict[str, Any]] = []
        skipped = 0
        unsupported_skipped = 0
        for row in rows:
            image_url = str(row.get("image_url") or "").strip()
            source_page = str(row.get("source_page") or "").strip()
            sticker_id = str(row.get("sticker_id") or "").strip()
            if not sticker_id or (not image_url and not source_page):
                skipped += 1
                continue
            ext = Path(urlparse(image_url or source_page).path).suffix.lower()
            if ext and ext not in ALLOWED_RASTER_EXTENSIONS:
                unsupported_skipped += 1
                continue
            candidates.append(
                {
                    "provider": self.name,
                    "sticker_id": sticker_id,
                    "query_id": "",
                    "source_page": source_page,
                    "image_url": image_url,
                    "local_path": "",
                    "executed_query": str(row.get("notes") or "").strip(),
                    "width": None,
                    "height": None,
                    "license_status": str(row.get("license_status") or "needs_manual_review").strip() or "needs_manual_review",
                    "relevance_score": 1.0,
                    "status": "found",
                    "duplicate_group": None,
                }
            )
        return {
            "status": "ok",
            "provider": self.name,
            "message": "Manual URLs loaded.",
            "candidates": candidates,
            "rows_read": len(rows),
            "candidates_created": len(candidates),
            "duplicates_skipped": 0,
            "unsupported_skipped": unsupported_skipped,
            "useful_candidates": len(candidates),
            "skipped": skipped,
        }

    def _read_rows(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        import csv

        with path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

