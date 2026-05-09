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
    assert "Providers permitidos" in out


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


def test_cmd_build_sticker_candidates_skips_review(monkeypatch, capsys) -> None:
    calls = []

    class FakeQueryBuilder:
        def run(self, payload=None):  # noqa: ANN001
            calls.append("search")
            return {"stickers_count": 1, "generated_queries": 1}

    class FakeRouter:
        def run(self, payload=None):  # noqa: ANN001
            calls.append("route")
            return {"routes_generated": 1}

    class FakeExecutor:
        def run(self, provider="auto", limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append("execute")
            return {"candidates_created": 1}

    class FakeEvaluator:
        def run(self, provider=None, limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append("evaluate")
            return {"kept_found": 1}

    class FakePreflight:
        def run(self, provider=None, limit=None, retry_only=False, force=False, sticker_ids=None):  # noqa: ANN001
            calls.append("preflight")
            return {"checked": 1}

    class FakeDownload:
        def run_download(self, provider=None, limit=None, require_approved=False, sticker_ids=None):  # noqa: ANN001
            calls.append("download")
            return {"downloaded": 1}

    class FakeCrop:
        def run(self, provider=None, limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append("crop")
            return {"cropped": 1}

    monkeypatch.setattr(main, "QueryBuilderAgent", FakeQueryBuilder)
    monkeypatch.setattr(main, "SearchRouterAgent", FakeRouter)
    monkeypatch.setattr(main, "SearchExecutorAgent", FakeExecutor)
    monkeypatch.setattr(main, "CandidateEvaluatorAgent", FakeEvaluator)
    monkeypatch.setattr(main, "CandidatePreflightAgent", FakePreflight)
    monkeypatch.setattr(main, "DownloadAgent", FakeDownload)
    monkeypatch.setattr(main, "CropAgent", FakeCrop)
    monkeypatch.setattr(
        main.db,
        "list_stickers",
        lambda conn: [
            {
                "sticker_id": "SL-01-001",
                "status": "planned",
            }
        ],
    )
    code = main.cmd_build_sticker_candidates(argparse.Namespace(provider="auto", limit=5))
    out = capsys.readouterr().out
    assert code == 0
    assert calls == ["search", "route", "execute", "evaluate", "preflight", "download", "crop"]
    assert "Build sticker candidates complete." in out


def test_cmd_build_sticker_candidates_keeps_trying_until_requested_count(monkeypatch, capsys) -> None:
    calls = []

    class FakeQueryBuilder:
        def run(self, payload=None):  # noqa: ANN001
            calls.append(f"search:{payload['sticker_ids'][0]}")
            return {"stickers_count": 1, "generated_queries": 1}

    class FakeRouter:
        def run(self, payload=None):  # noqa: ANN001
            calls.append(f"route:{payload['sticker_ids'][0] if payload and payload.get('sticker_ids') else 'all'}")
            return {"routes_generated": 1}

    class FakeExecutor:
        def run(self, provider="auto", limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append(f"execute:{sticker_ids[0]}")
            return {"candidates_created": 1}

    class FakeEvaluator:
        def run(self, provider=None, limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append(f"evaluate:{sticker_ids[0]}")
            return {"kept_found": 1}

    class FakePreflight:
        def run(self, provider=None, limit=None, retry_only=False, force=False, sticker_ids=None):  # noqa: ANN001
            calls.append(f"preflight:{sticker_ids[0]}")
            return {"checked": 1}

    class FakeDownload:
        def run_download(self, provider=None, limit=None, require_approved=False, sticker_ids=None):  # noqa: ANN001
            calls.append(f"download:{sticker_ids[0]}")
            return {"downloaded": 1}

    class FakeCrop:
        def run(self, provider=None, limit=None, sticker_ids=None):  # noqa: ANN001
            calls.append(f"crop:{sticker_ids[0]}")
            return {"cropped": 1}

    monkeypatch.setattr(main, "QueryBuilderAgent", FakeQueryBuilder)
    monkeypatch.setattr(main, "SearchRouterAgent", FakeRouter)
    monkeypatch.setattr(main, "SearchExecutorAgent", FakeExecutor)
    monkeypatch.setattr(main, "CandidateEvaluatorAgent", FakeEvaluator)
    monkeypatch.setattr(main, "CandidatePreflightAgent", FakePreflight)
    monkeypatch.setattr(main, "DownloadAgent", FakeDownload)
    monkeypatch.setattr(main, "CropAgent", FakeCrop)
    monkeypatch.setattr(
        main.db,
        "list_stickers",
        lambda conn: [
            {"sticker_id": "SL-01-001", "status": "planned"},
            {"sticker_id": "SL-01-002", "status": "planned"},
            {"sticker_id": "SL-01-003", "status": "planned"},
        ],
    )

    code = main.cmd_build_sticker_candidates(argparse.Namespace(provider="auto", limit=2))
    out = capsys.readouterr().out
    assert code == 0
    assert calls == [
        "search:SL-01-001",
        "route:SL-01-001",
        "execute:SL-01-001",
        "evaluate:SL-01-001",
        "preflight:SL-01-001",
        "download:SL-01-001",
        "crop:SL-01-001",
        "search:SL-01-002",
        "route:SL-01-002",
        "execute:SL-01-002",
        "evaluate:SL-01-002",
        "preflight:SL-01-002",
        "download:SL-01-002",
        "crop:SL-01-002",
    ]
    assert "Requested count: 2" in out
