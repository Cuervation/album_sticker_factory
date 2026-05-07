import argparse

import main


def test_cmd_evaluate_candidates_no_data_message(monkeypatch, capsys) -> None:
    class EmptyEvaluator:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            return {
                "status": "ok",
                "candidates_read": 0,
                "candidates_evaluated": 0,
                "needs_review": 0,
                "technical_rejected": 0,
                "semantic_rejected": 0,
                "kept_found": 0,
                "csv_path": "data/image_candidates.csv",
                "message": "No hay candidatos para evaluar. Ejecuta primero execute-routes.",
            }

    monkeypatch.setattr(main, "CandidateEvaluatorAgent", EmptyEvaluator)
    code = main.cmd_evaluate_candidates(argparse.Namespace(provider="wikimedia", limit=50))
    out = capsys.readouterr().out
    assert code == 0
    assert "No hay candidatos para evaluar" in out


def test_cmd_evaluate_candidates_prints_summary(monkeypatch, capsys) -> None:
    captured = {}

    class SuccessfulEvaluator:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            captured["provider"] = provider
            captured["limit"] = limit
            return {
                "status": "ok",
                "candidates_read": 20,
                "candidates_evaluated": 20,
                "needs_review": 12,
                "technical_rejected": 5,
                "semantic_rejected": 3,
                "kept_found": 0,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "CandidateEvaluatorAgent", SuccessfulEvaluator)
    code = main.cmd_evaluate_candidates(argparse.Namespace(provider="wikimedia", limit=20))
    out = capsys.readouterr().out
    assert code == 0
    assert "Candidate evaluation complete." in out
    assert "Candidates evaluated: 20" in out
    assert "technical_rejected: 5" in out
    assert "No se descargaron imagenes; solo se evaluo metadata." in out
    assert captured["provider"] == "wikimedia"
    assert captured["limit"] == 20
