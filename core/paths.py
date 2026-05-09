"""Path constants and directory helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]

CONFIG_PATH = ROOT_DIR / "config.yaml"
CHAPTERS_CSV_PATH = ROOT_DIR / "data" / "chapters.csv"
STICKER_TARGETS_CSV_PATH = ROOT_DIR / "data" / "sticker_targets.csv"
SEARCH_QUERIES_CSV_PATH = ROOT_DIR / "data" / "search_queries.csv"
SEARCH_ROUTES_CSV_PATH = ROOT_DIR / "data" / "search_routes.csv"
IMAGE_CANDIDATES_CSV_PATH = ROOT_DIR / "data" / "image_candidates.csv"
REVIEW_DECISIONS_CSV_PATH = ROOT_DIR / "data" / "review_decisions.csv"
CURATION_SEED_PATH = ROOT_DIR / "data" / "curation_seed.json"
DB_PATH = ROOT_DIR / "metadata" / "stickers.sqlite"
INPUT_DIR = ROOT_DIR / "input"
LOCAL_IMAGES_DIR = INPUT_DIR / "local_images"

OUTPUT_DIR = ROOT_DIR / "output"
STICKERS_DIR = OUTPUT_DIR / "stickers"
STICKERS_MANIFEST_CSV_PATH = OUTPUT_DIR / "stickers_manifest.csv"
REVIEW_REPORT_HTML_PATH = ROOT_DIR / "reports" / "review_candidates.html"
RUNTIME_DIRECTORIES = [
    ROOT_DIR / "metadata",
    LOCAL_IMAGES_DIR,
    OUTPUT_DIR / "raw",
    STICKERS_DIR,
    OUTPUT_DIR / "candidates",
    OUTPUT_DIR / "processed",
    OUTPUT_DIR / "review",
    OUTPUT_DIR / "approved",
    OUTPUT_DIR / "rejected",
    ROOT_DIR / "reports",
]


def ensure_directories(paths: Iterable[Path]) -> None:
    """Ensure directory paths exist."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
