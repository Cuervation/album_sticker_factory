import argparse
from pathlib import Path

import main
from agents.candidate_preflight_agent import CandidatePreflightAgent
from core import db


class _Resp:
    def __init__(self, content_type: str, content_length: str = "1234") -> None:
        self.headers = {"Content-Type": content_type, "Content-Length": content_length}

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
            "use_head_first": True,
            "fallback_to_range_get": True,
            "user_agent": "test-agent",
            "mark_non_image_as_technical_rejected": True,
            "keep_429_as_retryable": True,
        },
        "preflight_retry": {
            "enabled": True,
            "statuses_to_retry": ["retryable"],
            "max_candidates_per_run": 20,
            "min_seconds_between_retries": 300,
            "max_retry_attempts": 3,
            "retryable_errors": ["http_error:429", "timeout", "url_error"],
        },
    }


def _seed(conn, image_id: str, *, status: str = "found", provider: str = "wikimedia") -> None:
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-01-001",
                "query_id": "Q-SL-01-001-01",
                "provider": provider,
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
                "status": status,
            }
        ],
    )


def test_cmd_preflight_candidates_message(monkeypatch, capsys) -> None:
    class FakeAgent:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            return {
                "status": "ok",
                "candidates_read": 0,
                "checked": 0,
                "passed": 0,
                "blocked": 0,
                "retryable": 0,
                "failed": 0,
                "technical_rejected": 0,
                "csv_path": "data/image_candidates.csv",
                "message": "No hay candidatos para preflight con esos filtros.",
            }

    monkeypatch.setattr(main, "CandidatePreflightAgent", FakeAgent)
    code = main.cmd_preflight_candidates(argparse.Namespace(provider="wikimedia", limit=50))
    out = capsys.readouterr().out
    assert code == 0
    assert "No hay candidatos para preflight" in out


def test_cmd_preflight_candidates_summary(monkeypatch, capsys) -> None:
    class FakeAgent:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            return {
                "status": "ok",
                "candidates_read": 20,
                "checked": 20,
                "passed": 11,
                "blocked": 5,
                "retryable": 2,
                "failed": 2,
                "technical_rejected": 5,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "CandidatePreflightAgent", FakeAgent)
    code = main.cmd_preflight_candidates(argparse.Namespace(provider="wikimedia", limit=20))
    out = capsys.readouterr().out
    assert code == 0
    assert "Candidate preflight complete." in out
    assert "Blocked: 5" in out


def test_cmd_retry_preflight_summary(monkeypatch, capsys) -> None:
    class FakeAgent:
        def run(self, provider=None, limit=None, retry_only=False, force=False):  # noqa: ANN001
            assert retry_only is True
            return {
                "status": "ok",
                "candidates_read": 10,
                "checked": 5,
                "passed": 2,
                "blocked": 1,
                "retryable": 2,
                "failed": 0,
                "technical_rejected": 1,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "CandidatePreflightAgent", FakeAgent)
    code = main.cmd_retry_preflight(argparse.Namespace(provider="wikimedia", limit=5, force=False))
    out = capsys.readouterr().out
    assert code == 0
    assert "Retry preflight complete." in out


def test_cmd_mark_for_retry_summary(monkeypatch, capsys) -> None:
    class FakeAgent:
        def mark_for_retry(self, provider=None, image_id=None, limit=None, reason="", preflight_status="retryable", dry_run=False):  # noqa: ANN001
            assert provider == "wikimedia"
            assert reason == "manual retry test"
            assert dry_run is True
            return {
                "status": "ok",
                "provider": provider,
                "candidates_matched": 1,
                "marked": 0,
                "dry_run": True,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "CandidatePreflightAgent", FakeAgent)
    code = main.cmd_mark_for_retry(
        argparse.Namespace(provider="wikimedia", image_id=None, limit=1, reason="manual retry test", status="retryable", dry_run=True)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Mark for retry complete." in out
    assert "Dry run: True" in out


def test_cmd_force_retry_now_summary(monkeypatch, capsys) -> None:
    class FakeAgent:
        def force_retry_now(self, provider=None, image_id=None, limit=None, reason="", dry_run=False):  # noqa: ANN001
            assert provider == "wikimedia"
            assert reason == "manual retry test"
            assert dry_run is True
            return {
                "status": "ok",
                "provider": provider,
                "candidates_matched": 1,
                "forced_marked": 0,
                "checked": 0,
                "passed": 0,
                "blocked": 0,
                "retryable": 0,
                "failed": 0,
                "technical_rejected": 0,
                "skipped_by_max_retry_attempts": 1,
                "skipped_by_retry_window": 0,
                "skipped_by_status": 0,
                "skipped_by_missing_url": 0,
                "skipped_by_other_reason": 0,
                "dry_run": True,
                "csv_path": "data/image_candidates.csv",
                "skip_summary": "max_retry_attempts=1",
            }

    monkeypatch.setattr(main, "CandidatePreflightAgent", FakeAgent)
    code = main.cmd_force_retry_now(
        argparse.Namespace(provider="wikimedia", image_id=None, limit=1, reason="manual retry test", dry_run=True)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Force retry now complete." in out
    assert "Dry run: True" in out
    assert "Skip summary: max_retry_attempts=1" in out


def test_cmd_force_retry_now_sqlite_integration(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-CLI-1")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429', preflight_retry_count=0 WHERE image_id='IMG-CLI-1'"
        )
        conn.commit()
    finally:
        conn.close()

    class Factory:
        def __call__(self):  # noqa: ANN001
            return CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv")

    monkeypatch.setattr("agents.candidate_preflight_agent.load_config", _cfg)
    monkeypatch.setattr("agents.candidate_preflight_agent.urlopen", lambda req, timeout=0: _Resp("image/jpeg", "10"))
    monkeypatch.setattr(main, "CandidatePreflightAgent", Factory())
    code = main.cmd_force_retry_now(
        argparse.Namespace(provider="wikimedia", image_id="IMG-CLI-1", limit=1, reason="manual retry test", dry_run=False)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Checked: 1" in out
    assert "skipped_by_preflight_status: 0" in out


def test_cmd_force_retry_now_sqlite_skip_keeps_dry_run_false(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed(conn, "IMG-CLI-2", status="found")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='blocked', preflight_error='unsupported_content_type:image/vnd.djvu' WHERE image_id='IMG-CLI-2'"
        )
        conn.commit()
    finally:
        conn.close()

    class Factory:
        def __call__(self):  # noqa: ANN001
            return CandidatePreflightAgent(db_path=db_path, output_csv_path=tmp_path / "out.csv")

    monkeypatch.setattr(main, "CandidatePreflightAgent", Factory())
    code = main.cmd_force_retry_now(
        argparse.Namespace(provider="wikimedia", image_id="IMG-CLI-2", limit=1, reason="manual retry test", dry_run=False)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Dry run: False" in out
    assert "skipped_by_preflight_status: 1" in out


def test_new_retry_commands_require_reason() -> None:
    parser = main.build_parser()
    try:
        parser.parse_args(["mark-for-retry", "--provider", "wikimedia"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("Expected parser failure")

    args = parser.parse_args(["force-retry-now", "--provider", "wikimedia", "--reason", "manual retry test", "--dry-run"])
    assert args.command == "force-retry-now"
    assert args.dry_run is True
