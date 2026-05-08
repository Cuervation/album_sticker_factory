import argparse

import main


def test_cmd_execute_routes_handles_missing_routes(monkeypatch, capsys) -> None:
    class MissingRoutesExecutor:
        def run(self, provider="local_folder", limit=None):  # noqa: ANN001
            raise ValueError("No search routes found. Primero ejecuta python main.py route-search")

    monkeypatch.setattr(main, "SearchExecutorAgent", MissingRoutesExecutor)
    code = main.cmd_execute_routes(argparse.Namespace(provider="local_folder", limit=10))
    out = capsys.readouterr().out
    assert code == 0
    assert "Primero ejecuta python main.py route-search" in out


def test_cmd_execute_routes_rejects_external_provider(monkeypatch, capsys) -> None:
    class ExternalDeniedExecutor:
        def run(self, provider="local_folder", limit=None):  # noqa: ANN001
            raise ValueError("Prompt 8 only allows provider=local_folder or provider=wikimedia.")

    monkeypatch.setattr(main, "SearchExecutorAgent", ExternalDeniedExecutor)
    code = main.cmd_execute_routes(argparse.Namespace(provider="general_web", limit=10))
    out = capsys.readouterr().out
    assert code == 0
    assert "solo se permite --provider local_folder" in out


def test_cmd_execute_routes_prints_summary(monkeypatch, capsys) -> None:
    class SuccessfulExecutor:
        def run(self, provider="local_folder", limit=None):  # noqa: ANN001
            return {
                "provider": "local_folder",
                "routes_read": 50,
                "routes_executed": 50,
                "images_found": 5,
                "candidates_created": 2,
                "routes_routed": 10,
                "routes_skipped": 40,
                "routes_failed": 0,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "SearchExecutorAgent", SuccessfulExecutor)
    code = main.cmd_execute_routes(argparse.Namespace(provider="local_folder", limit=50))
    out = capsys.readouterr().out
    assert code == 0
    assert "Route execution complete." in out
    assert "Candidates found: 2" in out
    assert "Candidates created: 2" in out
    assert "No se descargaron imagenes" in out


def test_cmd_execute_routes_wikimedia_path(monkeypatch, capsys) -> None:
    class SuccessfulExecutor:
        def run(self, provider="local_folder", limit=None):  # noqa: ANN001
            return {
                "provider": provider,
                "routes_read": 2,
                "routes_executed": 2,
                "images_found": 0,
                "candidates_created": 3,
                "routes_routed": 2,
                "routes_skipped": 0,
                "routes_failed": 0,
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "SearchExecutorAgent", SuccessfulExecutor)
    code = main.cmd_execute_routes(argparse.Namespace(provider="wikimedia", limit=2))
    out = capsys.readouterr().out
    assert code == 0
    assert "Provider: wikimedia" in out
    assert "Routes executed: 2" in out
