import csv
from pathlib import Path

from agents.review_agent import ReviewAgent
from core import db


def _seed_candidate(conn, image_id: str, status: str = "needs_review") -> None:
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-13-001",
                "query_id": "Q-SL-13-001-01",
                "provider": "wikimedia",
                "source_page": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                "image_url": "https://upload.wikimedia.org/test.jpg",
                "local_path": "",
                "executed_query": "San Lorenzo Libertadores 2014",
                "width": 1200,
                "height": 800,
                "quality_score": None,
                "relevance_score": 0.8,
                "duplicate_group": None,
                "license_status": "attribution_required",
                "status": status,
                "metadata_score": 0.7,
                "decision_reason": "seed",
                "evaluated_at": "2026-05-07T12:00:00Z",
                "preflight_status": "",
                "preflight_error": "",
                "preflight_content_type": "",
                "preflight_content_length": None,
                "preflight_checked_at": "",
            }
        ],
    )


def _review_cfg(base: Path) -> dict:
    return {
        "review": {
            "html_report_path": str(base / "review_candidates.html"),
            "decisions_csv_path": str(base / "review_decisions.csv"),
            "default_reviewer": "local_user",
            "allow_remote_image_preview": True,
        },
        "review_safety": {
            "block_approval_if_preflight_blocked": True,
            "block_approval_if_preflight_retryable": True,
            "block_approval_if_preflight_missing": False,
            "allow_override_column": True,
            "override_value": "force_approved",
            "require_override_note": True,
        },
    }


def test_review_candidates_generates_html_and_csv(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, "IMG-1")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='blocked', preflight_error='invalid_content_type:application/pdf', preflight_content_type='application/pdf' WHERE image_id='IMG-1'"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("agents.review_agent.load_config", lambda: _review_cfg(tmp_path))
    result = ReviewAgent(db_path=db_path).review_candidates()
    assert result["candidates_needs_review"] == 1
    html_path = tmp_path / "review_candidates.html"
    csv_path = tmp_path / "review_decisions.csv"
    assert html_path.exists()
    assert csv_path.exists()
    html_text = html_path.read_text(encoding="utf-8")
    assert "https://upload.wikimedia.org/test.jpg" in html_text
    assert "https://commons.wikimedia.org/wiki/File:Test.jpg" in html_text
    assert "preflight_status" in html_text
    assert "invalid_content_type:application/pdf" in html_text

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["image_id"] == "IMG-1"
    assert rows[0]["review_status"] == ""


def test_review_candidates_preserves_existing_decisions(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "review_decisions.csv"
    csv_path.write_text("image_id,review_status,notes\nIMG-OLD,approved,ok\n", encoding="utf-8")
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, "IMG-NEW")
    finally:
        conn.close()

    monkeypatch.setattr("agents.review_agent.load_config", lambda: _review_cfg(tmp_path))
    ReviewAgent(db_path=db_path).review_candidates()
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = reader.fieldnames or []
    by_id = {row["image_id"]: row for row in rows}
    assert "IMG-OLD" in by_id
    assert "IMG-NEW" in by_id
    assert by_id["IMG-OLD"]["review_status"] == "approved"
    assert "preflight_status" in headers
    assert "preflight_error" in headers
    assert "preflight_content_type" in headers


def test_apply_reviews_updates_status_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    decisions = tmp_path / "review_decisions.csv"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, "IMG-A")
        _seed_candidate(conn, "IMG-R")
        _seed_candidate(conn, "IMG-M")
        _seed_candidate(conn, "IMG-U")
        _seed_candidate(conn, "IMG-BLOCK")
        _seed_candidate(conn, "IMG-RET")
        _seed_candidate(conn, "IMG-FORCE")
        _seed_candidate(conn, "IMG-FORCE-PDF")
        conn.execute("UPDATE image_candidates SET preflight_status='passed' WHERE image_id='IMG-A'")
        conn.execute("UPDATE image_candidates SET preflight_status='blocked', preflight_error='invalid_content_type:application/pdf', preflight_content_type='application/pdf' WHERE image_id='IMG-BLOCK'")
        conn.execute("UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-RET'")
        conn.execute("UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-FORCE'")
        conn.execute("UPDATE image_candidates SET preflight_status='blocked', preflight_error='invalid_content_type:application/pdf', preflight_content_type='application/pdf' WHERE image_id='IMG-FORCE-PDF'")
        conn.commit()
    finally:
        conn.close()
    decisions.write_text(
        (
            "image_id,review_status,notes\n"
            "IMG-A,approved,bien\n"
            "IMG-R,rejected,mal\n"
            "IMG-M,needs_more_info,duda\n"
            "IMG-U,,\n"
            "IMG-BLOCK,approved,try\n"
            "IMG-RET,approved,try\n"
            "IMG-FORCE,force_approved,manual override\n"
            "IMG-FORCE-PDF,force_approved,manual override\n"
            "IMG-BAD,invalid,xx\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("agents.review_agent.load_config", lambda: _review_cfg(tmp_path))
    agent = ReviewAgent(db_path=db_path)
    first = agent.apply_reviews()
    second = agent.apply_reviews()
    assert first["approved_applied"] == 1
    assert first["force_approved_applied"] == 1
    assert first["rejected_applied"] == 1
    assert first["needs_more_info_applied"] == 1
    assert first["unchanged"] == 1
    assert first["blocked_by_safety"] == 3
    assert first["invalid_rows"] == 1
    assert second["reviews_upserted"] >= 6

    conn = db.get_connection(db_path)
    try:
        statuses = {
            row["image_id"]: row["status"]
            for row in conn.execute("SELECT image_id, status FROM image_candidates").fetchall()
        }
        reviews_total = db.count_rows(conn, "reviews")
        review_status = db.get_reviews_by_status(conn)
    finally:
        conn.close()
    assert statuses["IMG-A"] == "approved"
    assert statuses["IMG-R"] == "rejected"
    assert statuses["IMG-M"] == "needs_review"
    assert statuses["IMG-U"] == "needs_review"
    assert statuses["IMG-BLOCK"] == "needs_review"
    assert statuses["IMG-RET"] == "needs_review"
    assert statuses["IMG-FORCE"] == "approved"
    assert statuses["IMG-FORCE-PDF"] == "needs_review"
    assert reviews_total >= 6
    assert review_status["approved"] == 1
    assert review_status["rejected"] == 1
    assert review_status["needs_more_info"] == 4


def test_review_candidates_handles_empty_list(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
    finally:
        conn.close()
    monkeypatch.setattr("agents.review_agent.load_config", lambda: _review_cfg(tmp_path))
    result = ReviewAgent(db_path=db_path).review_candidates()
    assert result["candidates_needs_review"] == 0
