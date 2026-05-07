import csv
from pathlib import Path

from agents.search_executor_agent import SearchExecutorAgent
from core import db


def _base_config(local_dir: Path, allow_internet: bool = True) -> dict:
    return {
        "search_execution": {
            "enabled": True,
            "execute_providers": {
                "local_folder": True,
                "wikimedia": True,
                "general_web": False,
                "image_search": False,
                "webpage": False,
            },
            "max_routes_per_run": 20,
            "dry_run": False,
        },
        "local_sources": {
            "local_images_dir": str(local_dir),
            "allowed_extensions": [".jpg", ".jpeg", ".png", ".webp"],
        },
        "external_search": {
            "enabled": True,
            "allow_internet": allow_internet,
            "allowed_real_providers": ["wikimedia"],
            "user_agent": "test-agent",
            "timeout_seconds": 5,
            "max_results_per_route": 5,
            "max_routes_per_run": 20,
        },
    }


def _seed_minimal_query_route(conn, provider: str = "local_folder", route_id_suffix: str | None = None) -> None:
    db.create_tables(conn)
    conn.execute(
        """
        INSERT INTO stickers (
            sticker_id, chapter_id, chapter_title, chapter_slug, category,
            target_name, rarity, priority, search_hint, status, created_at, updated_at
        ) VALUES ('SL-13-001','13','Libertadores 2014','libertadores-2014','jugador',
                  'Nestor Ortigoza y el penal de la final','epica','alta',
                  'San Lorenzo Libertadores 2014 Ortigoza penal final','planned','now','now')
        """
    )
    conn.execute(
        """
        INSERT INTO search_queries (query_id, sticker_id, query, provider, status, created_at)
        VALUES ('Q-SL-13-001-01','SL-13-001',
                'San Lorenzo Libertadores 2014 Ortigoza penal final',
                'pending','pending','now')
        """
    )
    suffix = route_id_suffix or provider.replace("_", "-")
    conn.execute(
        """
        INSERT INTO search_routes (
            route_id, query_id, sticker_id, provider, priority, status, reason, created_at, updated_at
        ) VALUES (?, 'Q-SL-13-001-01', 'SL-13-001', ?, 1, 'pending', 'seeded', 'now', 'now')
        """,
        (f"R-Q-SL-13-001-01-{suffix}", provider),
    )
    conn.commit()


def test_executor_empty_folder_creates_zero_candidates(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    local_dir.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="local_folder")
    finally:
        conn.close()

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    output_csv = tmp_path / "image_candidates.csv"
    result = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=output_csv).run(
        provider="local_folder"
    )
    assert result["routes_read"] == 1
    assert result["candidates_created"] == 0
    assert output_csv.exists()


def test_executor_creates_local_candidates_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "san_lorenzo_libertadores_2014_ortigoza.jpg").write_bytes(b"fake")
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="local_folder")
    finally:
        conn.close()

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    first = agent.run(provider="local_folder")
    second = agent.run(provider="local_folder")

    conn = db.get_connection(sqlite_path)
    try:
        total = db.count_rows(conn, "image_candidates")
    finally:
        conn.close()

    with (tmp_path / "image_candidates.csv").open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert first["candidates_created"] >= 1
    assert total >= 1
    assert len(rows) == total
    assert second["routes_read"] >= 0
    assert "executed_query" in rows[0]


def test_executor_runs_wikimedia_with_mock_provider(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    local_dir.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia")
    finally:
        conn.close()

    class FakeWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 2,
                "tried_queries": ["San Lorenzo 2014", "San Lorenzo Libertadores 2014"],
                "candidates": [
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Test.jpg",
                        "image_url": "https://upload.wikimedia.org/test.jpg",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.8,
                        "executed_query": "San Lorenzo Libertadores 2014",
                    }
                ],
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", FakeWikimediaProvider)

    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["candidates_created"] == 1
    assert result["routes_routed"] == 1
    assert result["query_variants_tried"] >= 1
    assert "San Lorenzo Libertadores 2014" in result["executed_query_examples"][0]

    # Second run should not duplicate routed routes by default.
    result2 = agent.run(provider="wikimedia", limit=5)
    assert result2["routes_read"] == 0

    conn = db.get_connection(sqlite_path)
    try:
        row = conn.execute(
            "SELECT status, reason FROM search_routes WHERE provider='wikimedia' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert "candidates_found:" in str(row["reason"])


def test_executor_rejects_external_provider(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    try:
        agent.run(provider="general_web")
    except ValueError as exc:
        assert "only allows provider=local_folder or provider=wikimedia" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for external provider")


def test_executor_blocks_wikimedia_when_internet_disabled(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia")
    finally:
        conn.close()

    monkeypatch.setattr(
        "agents.search_executor_agent.load_config",
        lambda: _base_config(local_dir, allow_internet=False),
    )
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    try:
        agent.run(provider="wikimedia")
    except ValueError as exc:
        assert "allow_internet is false" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError when internet disabled")


def test_executor_wikimedia_no_results_sets_tried_queries_reason(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-nores")
    finally:
        conn.close()

    class EmptyWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 3,
                "tried_queries": ["a", "b", "c"],
                "candidates": [],
                "had_http_error": False,
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", EmptyWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["routes_skipped"] == 1

    conn = db.get_connection(sqlite_path)
    try:
        row = conn.execute(
            "SELECT status, reason FROM search_routes WHERE route_id LIKE '%wikimedia-nores' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "skipped"
    assert "tried_queries:3" in str(row["reason"])


def test_executor_wikimedia_http_error_sets_failed_reason(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-httperr")
    finally:
        conn.close()

    class ErrorWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "error",
                "provider": "wikimedia",
                "error_type": "http_error",
                "error_detail": "503",
                "candidates": [],
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", ErrorWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["routes_failed"] == 1

    conn = db.get_connection(sqlite_path)
    try:
        row = conn.execute(
            "SELECT status, reason FROM search_routes WHERE route_id LIKE '%wikimedia-httperr' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"
    assert row["reason"] == "http_error:503"


def test_executor_wikimedia_no_candidates_after_parse_reason(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-parse")
    finally:
        conn.close()

    class ParseEmptyWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 2,
                "tried_queries": ["q1", "q2"],
                "candidates": [],
                "had_http_error": False,
                "had_successful_call": True,
                "raw_results_seen": True,
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", ParseEmptyWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["routes_skipped"] == 1

    conn = db.get_connection(sqlite_path)
    try:
        row = conn.execute(
            "SELECT status, reason FROM search_routes WHERE route_id LIKE '%wikimedia-parse' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "skipped"
    assert "no_candidates_after_parse" in str(row["reason"])
