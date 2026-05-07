"""Data models used by the local pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    chapter_id: str
    chapter_title: str
    slug: str
    target_count: int
    notes: str = ""


@dataclass(frozen=True)
class StickerTarget:
    sticker_id: str
    chapter_id: str
    chapter_title: str
    chapter_slug: str
    category: str
    target_name: str
    rarity: str
    priority: str
    search_hint: str
    status: str


@dataclass(frozen=True)
class ImageCandidate:
    image_id: str
    sticker_id: str
    query_id: str
    provider: str
    source_page: str
    image_url: str
    local_path: str
    width: int
    height: int
    quality_score: float
    relevance_score: float
    duplicate_group: str
    license_status: str
    status: str

