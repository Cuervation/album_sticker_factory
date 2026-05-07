import csv
from pathlib import Path

from agents.candidate_evaluator_agent import CandidateEvaluatorAgent
from core import db


def _eval_config() -> dict:
    return {
        "candidate_evaluation": {
            "enabled": True,
            "min_width": 400,
            "min_height": 400,
            "preferred_min_width": 800,
            "preferred_min_height": 800,
            "min_relevance_score": 0.15,
            "require_image_url": True,
            "reject_missing_dimensions": False,
            "unknown_license_allowed_for_review": True,
        }
    }


def _seed_candidate(
    conn,
    *,
    image_id: str,
    provider: str = "wikimedia",
    image_url: str = "https://upload.wikimedia.org/test.jpg",
    source_page: str = "https://commons.wikimedia.org/wiki/File:Test.jpg",
    width: int | None = 1200,
    height: int | None = 800,
    relevance_score: float | None = 0.8,
    license_status: str = "attribution_required",
    status: str = "found",
) -> None:
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-13-001",
                "query_id": "Q-SL-13-001-01",
                "provider": provider,
                "source_page": source_page,
                "image_url": image_url,
                "local_path": "",
                "executed_query": "San Lorenzo Libertadores 2014",
                "width": width,
                "height": height,
                "quality_score": None,
                "relevance_score": relevance_score,
                "duplicate_group": None,
                "license_status": license_status,
                "status": status,
            }
        ],
    )


def test_candidate_evaluator_classifies_by_metadata(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "image_candidates.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, image_id="IMG-OK-1")
        _seed_candidate(conn, image_id="IMG-NOURL-1", image_url="", source_page="")
        _seed_candidate(conn, image_id="IMG-LOWDIM-1", width=200, height=200)
        _seed_candidate(conn, image_id="IMG-MISSDIM-1", width=None, height=None, license_status="unknown")
        _seed_candidate(conn, image_id="IMG-LOWREL-1", relevance_score=0.05)
        _seed_candidate(conn, image_id="IMG-REST-1", license_status="restricted")
    finally:
        conn.close()

    monkeypatch.setattr("agents.candidate_evaluator_agent.load_config", _eval_config)
    agent = CandidateEvaluatorAgent(db_path=sqlite_path, output_csv_path=csv_path)
    result = agent.run(provider="wikimedia")
    assert result["candidates_read"] == 6
    assert result["candidates_evaluated"] == 6
    assert result["needs_review"] == 2
    assert result["technical_rejected"] == 3
    assert result["semantic_rejected"] == 1
    assert result["kept_found"] == 0
    assert csv_path.exists()

    conn = db.get_connection(sqlite_path)
    try:
        rows = conn.execute(
            """
            SELECT image_id, status, metadata_score, decision_reason, evaluated_at
            FROM image_candidates
            ORDER BY image_id
            """
        ).fetchall()
    finally:
        conn.close()
    by_id = {row["image_id"]: row for row in rows}
    assert by_id["IMG-OK-1"]["status"] == "needs_review"
    assert float(by_id["IMG-OK-1"]["metadata_score"]) > 0
    assert "has_image_url" in str(by_id["IMG-OK-1"]["decision_reason"])
    assert by_id["IMG-NOURL-1"]["status"] == "technical_rejected"
    assert "missing_image_url" in str(by_id["IMG-NOURL-1"]["decision_reason"])
    assert by_id["IMG-LOWREL-1"]["status"] == "semantic_rejected"
    assert by_id["IMG-REST-1"]["status"] == "technical_rejected"
    assert by_id["IMG-OK-1"]["evaluated_at"] is not None

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 6
    assert "metadata_score" in csv_rows[0]
    assert "decision_reason" in csv_rows[0]
    assert "evaluated_at" in csv_rows[0]


def test_candidate_evaluator_idempotent(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "image_candidates.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, image_id="IMG-OK-2")
    finally:
        conn.close()

    monkeypatch.setattr("agents.candidate_evaluator_agent.load_config", _eval_config)
    agent = CandidateEvaluatorAgent(db_path=sqlite_path, output_csv_path=csv_path)
    first = agent.run(provider="wikimedia")
    second = agent.run(provider="wikimedia")
    assert first["candidates_evaluated"] == 1
    assert second["candidates_evaluated"] == 1

    conn = db.get_connection(sqlite_path)
    try:
        total = db.count_rows(conn, "image_candidates")
        status_row = conn.execute(
            "SELECT status FROM image_candidates WHERE image_id = 'IMG-OK-2'"
        ).fetchone()
    finally:
        conn.close()
    assert total == 1
    assert status_row["status"] == "needs_review"


def test_candidate_evaluator_provider_and_limit(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "image_candidates.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, image_id="IMG-W-1", provider="wikimedia")
        _seed_candidate(conn, image_id="IMG-L-1", provider="local_folder", image_url="", source_page="")
    finally:
        conn.close()

    monkeypatch.setattr("agents.candidate_evaluator_agent.load_config", _eval_config)
    agent = CandidateEvaluatorAgent(db_path=sqlite_path, output_csv_path=csv_path)
    result = agent.run(provider="wikimedia", limit=1)
    assert result["candidates_read"] == 1
    assert result["candidates_evaluated"] == 1


def test_candidate_evaluator_rejects_preflight_non_image(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "image_candidates.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
        _seed_candidate(conn, image_id="IMG-PF-1")
        conn.execute(
            "UPDATE image_candidates SET preflight_content_type='application/pdf', preflight_status='blocked' WHERE image_id='IMG-PF-1'"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("agents.candidate_evaluator_agent.load_config", _eval_config)
    agent = CandidateEvaluatorAgent(db_path=sqlite_path, output_csv_path=csv_path)
    result = agent.run(provider="wikimedia")
    assert result["technical_rejected"] == 1


def test_candidate_evaluator_no_candidates_message(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "image_candidates.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
    finally:
        conn.close()

    monkeypatch.setattr("agents.candidate_evaluator_agent.load_config", _eval_config)
    agent = CandidateEvaluatorAgent(db_path=sqlite_path, output_csv_path=csv_path)
    result = agent.run()
    assert result["candidates_read"] == 0
    assert "No hay candidatos para evaluar" in str(result.get("message", ""))
