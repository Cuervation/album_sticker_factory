from pathlib import Path
from urllib.error import HTTPError, URLError

from agents.candidate_preflight_agent import CandidatePreflightAgent
from core import db


class _Resp:
    def __init__(self, content_type: str, content_length: str = "1234", status: int = 200) -> None:
        self.headers = {"Content-Type": content_type, "Content-Length": content_length}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


def _cfg() -> dict:
    return {
        "candidate_preflight": {
            "enabled": True,
            "statuses_to_check": ["needs_review", "approved"],
            "allowed_providers": ["wikimedia"],
            "timeout_seconds": 5,
            "max_candidates_per_run": 50,
            "max_file_size_mb": 1,
            "allowed_mime_prefixes": ["image/"],
            "blocked_content_types": ["application/pdf", "text/html"],
            "use_head_first": True,
            "fallback_to_range_get": True,
            "user_agent": "test-agent",
            "mark_non_image_as_technical_rejected": True,
            "keep_429_as_retryable": True,
        }
        ,
        "preflight_retry": {
            "enabled": True,
            "statuses_to_retry": ["retryable"],
            "max_candidates_per_run": 20,
            "min_seconds_between_retries": 300,
            "max_retry_attempts": 3,
            "retryable_errors": ["http_error:429", "timeout", "url_error"],
        },
    }


def _seed(conn, image_id: str, status: str = "needs_review", provider: str = "wikimedia", image_url: str = "https://x/a.jpg") -> None:
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-01-001",
                "query_id": "Q-SL-01-001-01",
                "provider": provider,
                "source_page": "https://commons.wikimedia.org/wiki/File:X.jpg",
                "image_url": image_url,
                "local_path": "",
                "executed_query": "San Lorenzo",
                "width": 1000,
                "height": 1000,
                "quality_score": None,
                "relevance_score": 0.5,
                "duplicate_group": None,
                "license_status": "attribution_required",
                "status": status,
            }
        ],
    )


def test_preflight_passed(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-1")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    assert result["passed"] == 1


def test_preflight_allows_raster_types(tmp_path: Path, monkeypatch) -> None:
    for content_type in ("image/png", "image/webp", "image/gif"):
        db_path = tmp_path / f"{content_type.replace('/', '_')}.sqlite"
        conn = db.get_connection(db_path)
        try:
            db.create_tables(conn)
            _seed(conn, f"IMG-{content_type.split('/')[-1].upper()}")
        finally:
            conn.close()
        monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
        monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0, ct=content_type: _Resp(ct))
        result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / f"{content_type}.csv").run()
        assert result["passed"] == 1


def test_preflight_blocks_djvu_and_tiff(tmp_path: Path, monkeypatch) -> None:
    for content_type in ("image/vnd.djvu", "image/tiff"):
        db_path = tmp_path / f"{content_type.replace('/', '_')}.sqlite"
        conn = db.get_connection(db_path)
        try:
            db.create_tables(conn)
            _seed(conn, f"IMG-{content_type.split('/')[-1].upper()}")
        finally:
            conn.close()
        monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
        monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0, ct=content_type: _Resp(ct))
        result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / f"{content_type}.csv").run()
        assert result["blocked"] == 1
        conn = db.get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT preflight_status, preflight_error FROM image_candidates WHERE image_id LIKE 'IMG-%' ORDER BY image_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert row["preflight_status"] == "blocked"
        assert str(row["preflight_error"]).startswith("unsupported_content_type:")


def test_preflight_pdf_blocked_and_rejected(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-2", status="approved")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("application/pdf"))
    CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT status, preflight_status FROM image_candidates WHERE image_id='IMG-2'").fetchone()
    finally:
        conn.close()
    assert row["preflight_status"] == "blocked"
    assert row["status"] == "technical_rejected"


def test_preflight_html_blocked(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-HTML")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("text/html"))
    CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT preflight_status, preflight_error FROM image_candidates WHERE image_id='IMG-HTML'").fetchone()
    finally:
        conn.close()
    assert row["preflight_status"] == "blocked"
    assert row["preflight_error"].startswith("unsupported_content_type:")


def test_preflight_429_retryable(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-3", status="approved")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)

    def _raise(req, timeout=0):  # noqa: ANN001
        raise HTTPError(req.full_url, 429, "too many", hdrs=None, fp=None)

    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", _raise)
    CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT status, preflight_status, preflight_error FROM image_candidates WHERE image_id='IMG-3'").fetchone()
    finally:
        conn.close()
    assert row["status"] == "approved"
    assert row["preflight_status"] == "retryable"
    assert row["preflight_error"] == "http_error:429"


def test_preflight_head_405_fallback_get(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-4")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    state = {"calls": 0}

    def _mock(req, timeout=0):  # noqa: ANN001
        state["calls"] += 1
        if req.get_method() == "HEAD":
            raise HTTPError(req.full_url, 405, "not allowed", hdrs=None, fp=None)
        return _Resp("image/png", "100")

    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", _mock)
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    assert result["passed"] == 1
    assert state["calls"] >= 2


def test_preflight_missing_url_skipped_and_provider_filtered(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-5", image_url="")
        _seed(conn, "IMG-6", provider="local_folder")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    assert result["checked"] >= 1


def test_preflight_file_too_large_and_url_error(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-7")
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", str(2 * 1024 * 1024)))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    assert result["blocked"] == 1

    conn = db.get_connection(db_path)
    try:
        conn.execute("UPDATE image_candidates SET status='approved', preflight_status=NULL WHERE image_id='IMG-7'")
        conn.commit()
    finally:
        conn.close()

    def _url_err(req, timeout=0):  # noqa: ANN001
        raise URLError("dns")

    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", _url_err)
    result2 = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run()
    assert result2["failed"] == 1


def test_retry_preflight_only_retryable_and_force(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-R1", status="found")
        _seed(conn, "IMG-R2", status="found")
        conn.execute("UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_checked_at='2026-05-07T00:00:00+00:00', preflight_retry_count=0 WHERE image_id='IMG-R1'")
        conn.execute("UPDATE image_candidates SET preflight_status='blocked', preflight_error='unsupported_content_type:image/vnd.djvu', preflight_checked_at='2026-05-07T00:00:00+00:00', preflight_retry_count=0 WHERE image_id='IMG-R2'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", "10"))
    agent = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv")
    res = agent.run(provider="wikimedia", limit=10, retry_only=True, force=False)
    assert res["checked"] == 1
    db_path_force = tmp_path / "db_force.sqlite"
    conn = db.get_connection(db_path_force)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-F1", status="found")
        _seed(conn, "IMG-F2", status="found")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_checked_at='2026-05-07T00:00:00+00:00', preflight_retry_count=0 WHERE image_id='IMG-F1'"
        )
        conn.execute(
            "UPDATE image_candidates SET preflight_status='blocked', preflight_error='unsupported_content_type:image/vnd.djvu', preflight_checked_at='2026-05-07T00:00:00+00:00', preflight_retry_count=0 WHERE image_id='IMG-F2'"
        )
        conn.commit()
    finally:
        conn.close()
    res_force = CandidatePreflightAgent(db_path=db_path_force, output_csv_path=tmp_path / "out_force.csv").run(
        provider="wikimedia",
        limit=10,
        retry_only=True,
        force=True,
    )
    assert res_force["checked"] >= 1


def test_retry_preflight_respects_max_attempts(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-R3", status="needs_review")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=3 WHERE image_id='IMG-R3'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp('image/jpeg'))
    res = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run(
        provider="wikimedia", retry_only=True, force=False
    )
    assert res["checked"] == 0


def test_mark_for_retry_requires_reason(tmp_path: Path) -> None:
    agent = CandidatePreflightAgent(db_path=tmp_path / "db.sqlite", output_csv_path=tmp_path / "out.csv")
    try:
        agent.mark_for_retry(reason="  ")
    except ValueError as exc:
        assert "reason is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_mark_for_retry_updates_traceability_without_status_change(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-M1", status="approved")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-M1'"
        )
        conn.commit()
    finally:
        conn.close()
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").mark_for_retry(
        provider="wikimedia",
        reason="manual retry test",
    )
    assert result["marked"] == 1
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status, retry_requested_reason, last_retry_mode FROM image_candidates WHERE image_id='IMG-M1'"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "approved"
    assert row["retry_requested_reason"] == "manual retry test"
    assert row["last_retry_mode"] == "manual"


def test_force_retry_now_requires_reason(tmp_path: Path) -> None:
    agent = CandidatePreflightAgent(db_path=tmp_path / "db.sqlite", output_csv_path=tmp_path / "out.csv")
    try:
        agent.force_retry_now(reason="")
    except ValueError as exc:
        assert "reason is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_force_retry_now_bypasses_window_not_max_attempts(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-F1", status="needs_review")
        _seed(conn, "IMG-F2", status="needs_review")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_checked_at='2099-01-01T00:00:00+00:00', preflight_retry_count=0 WHERE image_id='IMG-F1'"
        )
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=3 WHERE image_id='IMG-F2'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", "10"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").force_retry_now(
        provider="wikimedia",
        limit=10,
        reason="manual force",
    )
    assert result["candidates_matched"] == 2
    assert result["checked"] == 1
    conn = db.get_connection(db_path)
    try:
        f1 = conn.execute(
            "SELECT preflight_status, preflight_retry_count, retry_forced_reason, last_retry_mode FROM image_candidates WHERE image_id='IMG-F1'"
        ).fetchone()
        f2 = conn.execute(
            "SELECT preflight_status, preflight_retry_count FROM image_candidates WHERE image_id='IMG-F2'"
        ).fetchone()
    finally:
        conn.close()
    assert f1["preflight_status"] == "passed"
    assert f1["preflight_retry_count"] == 1
    assert f1["retry_forced_reason"] == "manual force"
    assert f1["last_retry_mode"] == "forced"
    assert f2["preflight_status"] == "retryable"
    assert f2["preflight_retry_count"] == 3
    assert result["skipped_by_max_retry_attempts"] == 1


def test_force_retry_now_image_id_targets_exact_candidate(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-G1", status="needs_review")
        _seed(conn, "IMG-G2", status="needs_review")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=0 WHERE image_id='IMG-G1'"
        )
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=0 WHERE image_id='IMG-G2'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", "10"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").force_retry_now(
        provider="wikimedia",
        image_id="IMG-G1",
        reason="manual force",
    )
    assert result["candidates_matched"] == 1
    assert result["checked"] == 1
    conn = db.get_connection(db_path)
    try:
        g1 = conn.execute("SELECT preflight_status FROM image_candidates WHERE image_id='IMG-G1'").fetchone()
        g2 = conn.execute("SELECT preflight_status FROM image_candidates WHERE image_id='IMG-G2'").fetchone()
    finally:
        conn.close()
    assert g1["preflight_status"] == "passed"
    assert g2["preflight_status"] == "retryable"


def test_force_retry_now_image_id_reports_blocked_skip(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-B1", status="found")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='blocked', preflight_error='unsupported_content_type:image/vnd.djvu' WHERE image_id='IMG-B1'"
        )
        conn.commit()
    finally:
        conn.close()

    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").force_retry_now(
        provider="wikimedia",
        image_id="IMG-B1",
        reason="manual force",
    )
    assert result["checked"] == 0
    assert result["skipped_by_preflight_status"] == 1
    assert result["dry_run"] is False
    assert "preflight_status no retryable" in result["message"]


def test_force_retry_now_image_id_reports_provider_skip(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-P1", status="found", provider="local_folder")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-P1'"
        )
        conn.commit()
    finally:
        conn.close()

    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").force_retry_now(
        provider="wikimedia",
        image_id="IMG-P1",
        reason="manual force",
    )
    assert result["checked"] == 0
    assert result["skipped_by_provider"] == 1
    assert result["dry_run"] is False
    assert "provider distinto" in result["message"]


def test_force_retry_now_does_not_approve_blocked_pdf(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-F3", status="needs_review")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=0 WHERE image_id='IMG-F3'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("application/pdf", "10"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").force_retry_now(
        provider="wikimedia",
        reason="manual force",
    )
    assert result["blocked"] == 1
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT status, preflight_status FROM image_candidates WHERE image_id='IMG-F3'").fetchone()
    finally:
        conn.close()
    assert row["status"] == "technical_rejected"
    assert row["preflight_status"] == "blocked"


def test_retry_preflight_counts_missing_url_skip(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-MISS", status="needs_review", image_url="")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-MISS'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", "10"))
    result = CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv").run(
        provider="wikimedia", retry_only=True, force=True
    )
    assert result["checked"] == 1
    assert result["skipped_by_missing_url"] == 1
