from pathlib import Path
from urllib.error import HTTPError, URLError

from agents.download_agent import DownloadAgent
from core import db


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg", status: int = 200) -> None:
        self._body = body
        self._pos = 0
        self.headers = {"Content-Type": content_type}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._pos
        if self._pos >= len(self._body):
            return b""
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


def _seed_sticker(conn) -> None:
    conn.execute(
        """
        INSERT INTO stickers (
            sticker_id, chapter_id, chapter_title, chapter_slug, category,
            target_name, rarity, priority, search_hint, status, created_at, updated_at
        ) VALUES ('SL-13-001','13','Libertadores 2014','libertadores-2014','jugador',
                  'Ortigoza','epica','alta','San Lorenzo Ortigoza','planned','now','now')
        """
    )
    conn.commit()


def _seed_candidate(conn, image_id: str, status: str, provider: str = "wikimedia", image_url: str = "https://x/y.jpg") -> None:
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-13-001",
                "query_id": "Q-SL-13-001-01",
                "provider": provider,
                "source_page": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                "image_url": image_url,
                "local_path": "",
                "executed_query": "San Lorenzo Libertadores 2014",
                "width": 1200,
                "height": 800,
                "quality_score": None,
                "relevance_score": 0.8,
                "duplicate_group": None,
                "license_status": "attribution_required",
                "status": status,
            }
        ],
    )


def _cfg(tmp_path: Path) -> dict:
    return {
        "download": {
            "enabled": True,
            "approved_only": True,
            "output_dir": str(tmp_path / "raw"),
            "max_candidates_per_run": 10,
            "timeout_seconds": 5,
            "max_file_size_mb": 2,
            "allowed_providers": ["wikimedia"],
            "allowed_extensions": [".jpg", ".jpeg", ".png", ".webp"],
            "allowed_mime_prefixes": ["image/"],
            "user_agent": "test-agent",
        }
    }


def test_download_agent_no_approved_returns_ok(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-1", "needs_review")
    finally:
        conn.close()
    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    result = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv").run()
    assert result["approved_read"] == 0
    assert result["downloaded"] == 0
    assert "No hay candidatos approved" in str(result.get("message", ""))


def test_download_agent_downloads_approved_and_updates_fields(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    out_csv = tmp_path / "image_candidates.csv"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-2", "approved")
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr("agents.download_agent.urlopen", lambda req, timeout=0: _FakeResponse(b"abc123", "image/jpeg"))
    agent = DownloadAgent(db_path=db_path, output_csv_path=out_csv)
    result = agent.run(provider="wikimedia", limit=5)
    assert result["approved_read"] == 1
    assert result["downloaded"] == 1
    assert out_csv.exists()

    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT status, local_path, file_sha256, file_size_bytes, downloaded_at FROM image_candidates WHERE image_id='IMG-2'"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "downloaded"
    assert str(row["local_path"])
    assert row["file_sha256"]
    assert int(row["file_size_bytes"]) == 6
    assert row["downloaded_at"]


def test_download_agent_idempotent_skips_existing_file(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-3", "approved")
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr("agents.download_agent.urlopen", lambda req, timeout=0: _FakeResponse(b"abc123", "image/jpeg"))
    agent = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv")
    first = agent.run(provider="wikimedia", limit=5)
    second = agent.run(provider="wikimedia", limit=5)
    assert first["downloaded"] == 1
    assert second["approved_read"] == 0


def test_download_agent_rejects_provider_and_content_type(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-4", "approved", provider="general_web")
        _seed_candidate(conn, "IMG-5", "approved", provider="wikimedia", image_url="https://x/file.bin")
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr("agents.download_agent.urlopen", lambda req, timeout=0: _FakeResponse(b"abc123", "text/html"))
    agent = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(limit=10)
    assert result["failed"] >= 1 or result["skipped"] >= 1

    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT image_id, status, download_error FROM image_candidates WHERE image_id IN ('IMG-4','IMG-5') ORDER BY image_id"
        ).fetchall()
    finally:
        conn.close()
    assert rows[0]["status"] == "approved"
    assert rows[0]["download_error"] in ("provider_not_allowed", "", None)
    assert "invalid_content_type" in str(rows[1]["download_error"])


def test_download_agent_http_and_url_errors(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-6", "approved", image_url="https://x/err.jpg")
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))

    def _http_error(req, timeout=0):  # noqa: ANN001
        raise HTTPError(req.full_url, 500, "server error", hdrs=None, fp=None)

    monkeypatch.setattr("agents.download_agent.urlopen", _http_error)
    agent = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(limit=5)
    assert result["failed"] == 1

    def _url_error(req, timeout=0):  # noqa: ANN001
        raise URLError("dns failure")

    monkeypatch.setattr("agents.download_agent.urlopen", _url_error)
    result2 = agent.run(limit=5)
    assert result2["failed"] == 1


def test_download_agent_skips_preflight_blocked(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-7", "approved")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='blocked', preflight_error='invalid_content_type:application/pdf' WHERE image_id='IMG-7'"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr("agents.download_agent.urlopen", lambda req, timeout=0: _FakeResponse(b"abc123", "image/jpeg"))
    result = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv").run(limit=5)
    assert result["downloaded"] == 0
    assert result["skipped"] == 1


def test_download_agent_skips_preflight_retryable(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-8", "approved")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='retryable', preflight_error='http_error:429' WHERE image_id='IMG-8'"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr("agents.download_agent.urlopen", lambda req, timeout=0: _FakeResponse(b"abc123", "image/jpeg"))
    result = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv").run(limit=5)
    assert result["downloaded"] == 0
    assert result["skipped"] == 1


def test_download_agent_skips_preflight_pdf_content_type(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = db.get_connection(db_path)
    try:
        db.create_tables(conn)
        _seed_sticker(conn)
        _seed_candidate(conn, "IMG-9", "approved")
        conn.execute(
            "UPDATE image_candidates SET preflight_status='passed', preflight_content_type='application/pdf' WHERE image_id='IMG-9'"
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("agents.download_agent.load_config", lambda: _cfg(tmp_path))
    result = DownloadAgent(db_path=db_path, output_csv_path=tmp_path / "image_candidates.csv").run(limit=5)
    assert result["downloaded"] == 0
    assert result["skipped"] == 1
