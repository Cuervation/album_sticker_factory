import argparse

import main


def test_cmd_review_candidates_summary(monkeypatch, capsys) -> None:
    class FakeReviewAgent:
        def run(self, payload=None):  # noqa: ANN001
            assert payload["action"] == "review-candidates"
            return {
                "status": "ok",
                "candidates_needs_review": 12,
                "html_path": "reports/review_candidates.html",
                "decisions_csv_path": "data/review_decisions.csv",
                "decisions_existing": 5,
                "decisions_added": 7,
            }

    monkeypatch.setattr(main, "ReviewAgent", FakeReviewAgent)
    code = main.cmd_review_candidates(argparse.Namespace(provider="wikimedia", limit=20))
    out = capsys.readouterr().out
    assert code == 0
    assert "Review candidates preparation complete." in out
    assert "Candidates needs_review: 12" in out


def test_cmd_apply_reviews_summary(monkeypatch, capsys) -> None:
    class FakeReviewAgent:
        def run(self, payload=None):  # noqa: ANN001
            assert payload["action"] == "apply-reviews"
            return {
                "status": "ok",
                "rows_read": 12,
                "approved_applied": 3,
                "force_approved_applied": 1,
                "rejected_applied": 2,
                "needs_more_info_applied": 1,
                "unchanged": 5,
                "blocked_by_safety": 2,
                "invalid_rows": 1,
            }

    monkeypatch.setattr(main, "ReviewAgent", FakeReviewAgent)
    code = main.cmd_apply_reviews(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "Manual reviews applied." in out
    assert "approved applied: 3" in out
    assert "force_approved applied: 1" in out
    assert "blocked_by_safety: 2" in out


def test_cmd_apply_reviews_missing_csv_message(monkeypatch, capsys) -> None:
    class FakeReviewAgent:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "rows_read": 0,
                "approved_applied": 0,
                "rejected_applied": 0,
                "needs_more_info_applied": 0,
                "unchanged": 0,
                "invalid_rows": 0,
                "message": "No existe data/review_decisions.csv. Ejecuta primero python main.py review-candidates",
            }

    monkeypatch.setattr(main, "ReviewAgent", FakeReviewAgent)
    code = main.cmd_apply_reviews(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "No existe data/review_decisions.csv" in out


def test_cmd_review_alias_works(monkeypatch, capsys) -> None:
    class FakeReviewAgent:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "candidates_needs_review": 1,
                "html_path": "reports/review_candidates.html",
                "decisions_csv_path": "data/review_decisions.csv",
                "decisions_existing": 0,
                "decisions_added": 1,
            }

    monkeypatch.setattr(main, "ReviewAgent", FakeReviewAgent)
    code = main.cmd_review_candidates(argparse.Namespace(provider=None, limit=None))
    out = capsys.readouterr().out
    assert code == 0
    assert "Review candidates preparation complete." in out
