import json
from pathlib import Path

from jsonschema import validate


def _load_schema(name: str) -> dict:
    path = Path("contracts") / name
    assert path.exists()
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_files_exist() -> None:
    for name in [
        "sticker.schema.json",
        "image_candidate.schema.json",
        "review.schema.json",
        "run.schema.json",
        "search_route.schema.json",
    ]:
        assert (Path("contracts") / name).exists()


def test_validate_min_examples() -> None:
    sticker_schema = _load_schema("sticker.schema.json")
    image_schema = _load_schema("image_candidate.schema.json")
    review_schema = _load_schema("review.schema.json")
    run_schema = _load_schema("run.schema.json")
    route_schema = _load_schema("search_route.schema.json")

    validate(
        {
            "sticker_id": "S-0001",
            "chapter_id": "01",
            "chapter_title": "Nace el Ciclón",
            "chapter_slug": "nace-el-ciclon",
            "category": "equipo",
            "target_name": "Fundación del club",
            "rarity": "common",
            "priority": "high",
            "search_hint": "San Lorenzo fundacion",
            "status": "planned",
        },
        sticker_schema,
    )
    validate(
        {
            "image_id": "IMG-1",
            "sticker_id": "S-0001",
            "query_id": "Q-1",
            "provider": "local_folder",
            "source_page": "local://example",
            "image_url": "local://image",
            "local_path": "output/raw/example.jpg",
            "width": 800,
            "height": 800,
            "quality_score": 0.9,
            "relevance_score": 0.9,
            "duplicate_group": "DG-1",
            "license_status": "clear",
            "status": "found",
            "executed_query": "San Lorenzo Libertadores 2014",
            "metadata_score": 0.78,
            "decision_reason": "has_image_url;has_source_page",
            "evaluated_at": "2026-05-07T12:00:00Z",
            "file_sha256": "abc123",
            "file_size_bytes": 1024,
            "downloaded_at": "2026-05-07T12:05:00Z",
            "download_error": "",
            "preflight_status": "passed",
            "preflight_error": "",
            "preflight_content_type": "image/jpeg",
            "preflight_content_length": 1024,
            "preflight_checked_at": "2026-05-07T12:04:00Z",
            "preflight_retry_count": 1,
            "preflight_last_retry_at": "2026-05-07T12:05:00Z",
            "retry_requested_at": "2026-05-07T12:01:00Z",
            "retry_requested_reason": "manual retry",
            "retry_forced_at": "2026-05-07T12:02:00Z",
            "retry_forced_reason": "manual force",
            "last_retry_mode": "forced",
        },
        image_schema,
    )
    validate(
        {
            "review_id": "R-1",
            "image_id": "IMG-1",
            "review_status": "approved",
            "notes": "OK",
            "reviewed_at": "2026-05-07T12:00:00Z",
        },
        review_schema,
    )
    validate(
        {
            "run_id": "RUN-1",
            "command": "init",
            "status": "ok",
            "started_at": "2026-05-07T12:00:00Z",
            "finished_at": "2026-05-07T12:00:01Z",
            "summary_json": "{}",
        },
        run_schema,
    )
    validate(
        {
            "route_id": "R-Q-SL-01-001-01-general-web",
            "query_id": "Q-SL-01-001-01",
            "sticker_id": "SL-01-001",
            "provider": "general_web",
            "priority": 3,
            "status": "pending",
            "reason": "baseline",
        },
        route_schema,
    )
