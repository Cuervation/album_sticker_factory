from pathlib import Path

from core import db


def test_create_tables_and_load_chapters(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        loaded = db.load_chapters_from_csv(conn, Path("data/chapters.csv"))
        assert loaded == 18
        assert db.count_rows(conn, "chapters") == 18
    finally:
        conn.close()


def test_status_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        db.load_chapters_from_csv(conn, Path("data/chapters.csv"))
        status = db.get_status_counts(conn)
    finally:
        conn.close()

    assert status["chapters_count"] == 18
    assert status["target_total"] == 600
    assert status["stickers_count"] == 0
    assert status["queries_count"] == 0
    assert status["image_candidates_count"] == 0


def test_image_candidates_has_evaluation_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        rows = conn.execute("PRAGMA table_info(image_candidates)").fetchall()
    finally:
        conn.close()
    columns = {row["name"] for row in rows}
    assert "executed_query" in columns
    assert "metadata_score" in columns
    assert "decision_reason" in columns
    assert "evaluated_at" in columns
    assert "file_sha256" in columns
    assert "file_size_bytes" in columns
    assert "downloaded_at" in columns
    assert "download_error" in columns
    assert "preflight_status" in columns
    assert "preflight_error" in columns
    assert "preflight_content_type" in columns
    assert "preflight_content_length" in columns
    assert "preflight_checked_at" in columns
    assert "preflight_retry_count" in columns
    assert "preflight_last_retry_at" in columns
    assert "retry_requested_at" in columns
    assert "retry_requested_reason" in columns
    assert "retry_forced_at" in columns
    assert "retry_forced_reason" in columns
    assert "last_retry_mode" in columns


def test_reviews_by_status_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        db.upsert_reviews(
            conn,
            [
                {
                    "review_id": "REV-1",
                    "image_id": "IMG-1",
                    "review_status": "approved",
                    "notes": "ok",
                    "reviewed_at": "2026-05-07T12:00:00Z",
                },
                {
                    "review_id": "REV-2",
                    "image_id": "IMG-2",
                    "review_status": "rejected",
                    "notes": "bad",
                    "reviewed_at": "2026-05-07T12:00:01Z",
                },
            ],
        )
        grouped = db.get_reviews_by_status(conn)
        status = db.get_status_counts(conn)
    finally:
        conn.close()
    assert grouped["approved"] == 1
    assert grouped["rejected"] == 1
    assert status["reviews_count"] == 2


def test_list_candidates_for_retry_mark_uses_preflight_status(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        db.upsert_image_candidates(
            conn,
            [
                {
                    "image_id": "IMG-RTRY",
                    "sticker_id": "SL-01-001",
                    "query_id": "Q-SL-01-001-01",
                    "provider": "wikimedia",
                    "source_page": "https://commons.wikimedia.org/wiki/File:X.jpg",
                    "image_url": "https://example.com/x.jpg",
                    "local_path": "",
                    "executed_query": "San Lorenzo",
                    "width": 1000,
                    "height": 1000,
                    "quality_score": None,
                    "relevance_score": 0.5,
                    "duplicate_group": None,
                    "license_status": "attribution_required",
                    "status": "found",
                    "preflight_status": "retryable",
                    "preflight_error": "http_error:429",
                },
                {
                    "image_id": "IMG-BLK",
                    "sticker_id": "SL-01-002",
                    "query_id": "Q-SL-01-002-01",
                    "provider": "wikimedia",
                    "source_page": "https://commons.wikimedia.org/wiki/File:Y.jpg",
                    "image_url": "https://example.com/y.jpg",
                    "local_path": "",
                    "executed_query": "San Lorenzo",
                    "width": 1000,
                    "height": 1000,
                    "quality_score": None,
                    "relevance_score": 0.5,
                    "duplicate_group": None,
                    "license_status": "attribution_required",
                    "status": "found",
                    "preflight_status": "blocked",
                    "preflight_error": "unsupported_content_type:image/vnd.djvu",
                },
            ],
        )
        rows = db.list_candidates_for_retry_mark(conn, preflight_statuses=("retryable",))
    finally:
        conn.close()
    assert [row["image_id"] for row in rows] == ["IMG-RTRY"]
