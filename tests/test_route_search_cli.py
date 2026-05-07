import argparse

import main


def test_cmd_route_search_handles_missing_queries(monkeypatch, capsys) -> None:
    class MissingQueriesRouter:
        def run(self, payload=None):  # noqa: ANN001
            raise ValueError("No search queries found. Primero ejecuta python main.py search")

    monkeypatch.setattr(main, "SearchRouterAgent", MissingQueriesRouter)
    code = main.cmd_route_search(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "Primero ejecuta python main.py search" in out


def test_cmd_route_search_prints_summary(monkeypatch, capsys) -> None:
    class SuccessfulRouter:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "queries_count": 3000,
                "active_providers": ["wikimedia", "general_web", "image_search", "webpage"],
                "routes_generated": 12000,
                "total_routes_in_db": 12000,
                "routes_by_provider": {
                    "general_web": 3000,
                    "image_search": 3000,
                    "webpage": 3000,
                    "wikimedia": 3000,
                },
                "routes_by_status": {"pending": 12000},
                "csv_path": "data/search_routes.csv",
            }

    monkeypatch.setattr(main, "SearchRouterAgent", SuccessfulRouter)
    code = main.cmd_route_search(argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "Local routing generation complete." in out
    assert "Routes generated: 12000" in out
    assert "No se consulto internet" in out
