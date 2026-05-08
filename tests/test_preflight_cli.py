import argparse

import main


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
