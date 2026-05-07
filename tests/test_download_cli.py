import argparse

import main


def test_cmd_download_approved_no_candidates_message(monkeypatch, capsys) -> None:
    class FakeDownloadAgent:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            return {
                "status": "ok",
                "approved_read": 0,
                "download_attempted": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "csv_path": "data/image_candidates.csv",
                "output_dir": "output/raw",
                "message": "No hay candidatos approved para descargar. Edita data/review_decisions.csv y ejecuta apply-reviews.",
            }

    monkeypatch.setattr(main, "DownloadAgent", FakeDownloadAgent)
    code = main.cmd_download_approved(argparse.Namespace(provider="wikimedia", limit=10))
    out = capsys.readouterr().out
    assert code == 0
    assert "No hay candidatos approved para descargar" in out


def test_cmd_download_approved_summary(monkeypatch, capsys) -> None:
    class FakeDownloadAgent:
        def run(self, provider=None, limit=None):  # noqa: ANN001
            return {
                "status": "ok",
                "approved_read": 5,
                "download_attempted": 5,
                "downloaded": 3,
                "skipped": 1,
                "failed": 1,
                "output_dir": "output/raw",
                "csv_path": "data/image_candidates.csv",
            }

    monkeypatch.setattr(main, "DownloadAgent", FakeDownloadAgent)
    code = main.cmd_download_approved(argparse.Namespace(provider="wikimedia", limit=5))
    out = capsys.readouterr().out
    assert code == 0
    assert "Approved download complete." in out
    assert "Downloaded: 3" in out
    assert "No se recortaron ni exportaron stickers." in out


def test_cmd_download_alias_message(capsys) -> None:
    code = main._command_map()["download"](argparse.Namespace())
    out = capsys.readouterr().out
    assert code == 0
    assert "download-approved" in out
