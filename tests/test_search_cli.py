import argparse

import main


def test_cmd_search_handles_missing_stickers(monkeypatch, capsys) -> None:
    class MissingStickersBuilder:
        def run(self, payload=None):  # noqa: ANN001
            raise ValueError("No stickers found. Primero ejecuta python main.py plan")

    monkeypatch.setattr(main, "QueryBuilderAgent", MissingStickersBuilder)
    code = main.cmd_search(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "Primero ejecuta python main.py plan" in out


def test_cmd_search_prints_summary(monkeypatch, capsys) -> None:
    class SuccessfulBuilder:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "stickers_count": 600,
                "queries_per_sticker": 5,
                "generated_queries": 3000,
                "total_queries_in_db": 3000,
                "csv_path": "data/search_queries.csv",
            }

    monkeypatch.setattr(main, "QueryBuilderAgent", SuccessfulBuilder)
    code = main.cmd_search(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "Local search query generation complete." in out
    assert "Queries generated: 3000" in out
    assert "No se consulto internet" in out

