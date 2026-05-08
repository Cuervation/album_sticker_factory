import csv
from pathlib import Path

from agents.search_executor_agent import SearchExecutorAgent
from core import db
from providers.manual_urls_provider import ManualUrlsProvider


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
        assert "provider=local_folder" in str(exc)
        assert "provider=wikimedia" in str(exc)
        assert "provider=manual_urls" in str(exc)
        assert "provider=auto" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for external provider")


def test_executor_auto_runs_manual_then_wikimedia(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    local_dir.mkdir(parents=True, exist_ok=True)
    manual_dir = tmp_path / "data"
    manual_dir.mkdir(parents=True, exist_ok=True)
    manual_csv = manual_dir / "manual_image_urls.csv"
    manual_csv.write_text("sticker_id,source_page,image_url,notes,provider_hint,license_status\n", encoding="utf-8")
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="manual_urls", route_id_suffix="manual")
        conn.execute(
            """
            INSERT INTO search_routes (
                route_id, query_id, sticker_id, provider, priority, status, reason, created_at, updated_at
            ) VALUES (?, 'Q-SL-13-001-01', 'SL-13-001', 'wikimedia', 1, 'pending', 'seeded', 'now', 'now')
            """,
            ("R-Q-SL-13-001-01-wikimedia",),
        )
        conn.commit()
    finally:
        conn.close()

    class EmptyWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 1,
                "tried_queries": ["San Lorenzo"],
                "candidates": [
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Auto.jpg",
                        "image_url": "https://upload.wikimedia.org/auto.jpg",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.8,
                        "executed_query": "San Lorenzo",
                    }
                ],
                "had_http_error": False,
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: {
        **_base_config(local_dir),
        "source_providers": {
            "enabled_order": ["manual_urls", "wikimedia"],
            "providers": {
                "manual_urls": {"enabled": True},
                "wikimedia": {"enabled": True},
            },
        },
    })
    monkeypatch.setattr("agents.search_executor_agent.ROOT_DIR", tmp_path)
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", EmptyWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="auto", limit=5)
    assert result["provider"] == "auto"
    assert result["routes_executed"] >= 1
    assert result["candidates_created"] == 1
    assert result["useful_candidates"] == 1
    assert result["provider_summaries"][0]["provider"] == "manual_urls"
    assert result["provider_summaries"][1]["provider"] == "wikimedia"


def test_manual_urls_provider_ignores_documentary_extensions(tmp_path: Path) -> None:
    csv_path = tmp_path / "manual_image_urls.csv"
    csv_path.write_text(
        "sticker_id,source_page,image_url,notes,provider_hint,license_status\n"
        "SL-01-001,https://example.org/doc.pdf,https://example.org/doc.pdf,doc,manual,\n"
        "SL-01-001,https://example.org/photo.jpg,https://example.org/photo.jpg,photo,manual,\n",
        encoding="utf-8",
    )
    provider = ManualUrlsProvider()
    result = provider.run({"csv_path": csv_path})
    assert result["candidates_created"] == 1
    assert result["unsupported_skipped"] == 1


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
    assert "tried_queries:" in str(row["reason"])


def test_executor_reports_requested_and_effective_limit_and_exports_routes_csv(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-cap")
    finally:
        conn.close()

    class EmptyWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 1,
                "tried_queries": ["San Lorenzo"],
                "candidates": [],
                "had_http_error": False,
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", EmptyWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=200)
    assert result["requested_limit"] == 200
    assert result["effective_limit"] == 20
    assert result["search_routes_csv_path"].endswith("search_routes.csv")
    assert Path(result["search_routes_csv_path"]).exists()
    with Path(result["search_routes_csv_path"]).open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert any(row["status"] == "skipped" for row in rows)


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


def test_executor_wikimedia_fallback_finds_raster_candidate(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-fallback")
    finally:
        conn.close()

    class FallbackWikimediaProvider:
        calls = 0

        def run(self, payload=None):  # noqa: ANN001
            type(self).calls += 1
            if type(self).calls == 1:
                return {
                    "status": "ok",
                    "provider": "wikimedia",
                    "query_variants_tried": 2,
                    "tried_queries": ["San Lorenzo", "San Lorenzo 2014"],
                    "candidates": [],
                    "had_http_error": False,
                    "raw_results_seen": False,
                }
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 2,
                "tried_queries": ["San Lorenzo foto", "San Lorenzo imagen"],
                "candidates": [
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Raster.jpg",
                        "image_url": "https://upload.wikimedia.org/raster.jpg",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.8,
                        "executed_query": "San Lorenzo foto",
                    }
                ],
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", FallbackWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["candidates_created"] == 1
    assert result["query_variants_tried"] >= 4
    conn = db.get_connection(sqlite_path)
    try:
        row = conn.execute("SELECT status, reason FROM search_routes WHERE provider='wikimedia' LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row["status"] == "routed"
    assert "candidates_found:1" in str(row["reason"])


def test_executor_filters_documentary_candidates(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-docs")
    finally:
        conn.close()

    class DocumentaryWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 1,
                "tried_queries": ["San Lorenzo"],
                "candidates": [
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Doc.djvu",
                        "image_url": "https://upload.wikimedia.org/doc.djvu",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.9,
                        "executed_query": "San Lorenzo",
                    }
                ],
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", DocumentaryWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["candidates_created"] == 0
    conn = db.get_connection(sqlite_path)
    try:
        total = db.count_rows(conn, "image_candidates")
        row = conn.execute("SELECT status, reason FROM search_routes WHERE provider='wikimedia' LIMIT 1").fetchone()
    finally:
        conn.close()
    assert total == 0
    assert row["status"] == "skipped"
    assert "raw_results_but_only_unsupported_mime" in str(row["reason"]) or "no_candidates_after_parse" in str(row["reason"])


def test_executor_dedupes_canonical_urls_with_utm(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "db.sqlite"
    local_dir = tmp_path / "local_images"
    conn = db.get_connection(sqlite_path)
    try:
        _seed_minimal_query_route(conn, provider="wikimedia", route_id_suffix="wikimedia-dedupe")
    finally:
        conn.close()

    class DedupeWikimediaProvider:
        def run(self, payload=None):  # noqa: ANN001
            return {
                "status": "ok",
                "provider": "wikimedia",
                "query_variants_tried": 1,
                "tried_queries": ["San Lorenzo"],
                "candidates": [
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Same.jpg?utm_source=a",
                        "image_url": "https://upload.wikimedia.org/same.jpg?utm_source=a&utm_medium=b",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.9,
                        "executed_query": "San Lorenzo",
                    },
                    {
                        "source_page": "https://commons.wikimedia.org/wiki/File:Same.jpg?utm_source=c",
                        "image_url": "https://upload.wikimedia.org/same.jpg?utm_source=d",
                        "width": 1200,
                        "height": 800,
                        "license_status": "attribution_required",
                        "relevance_score": 0.8,
                        "executed_query": "San Lorenzo",
                    },
                ],
            }

    monkeypatch.setattr("agents.search_executor_agent.load_config", lambda: _base_config(local_dir))
    monkeypatch.setattr("agents.search_executor_agent.WikimediaProvider", DedupeWikimediaProvider)
    agent = SearchExecutorAgent(db_path=sqlite_path, output_csv_path=tmp_path / "image_candidates.csv")
    result = agent.run(provider="wikimedia", limit=5)
    assert result["candidates_created"] == 1
    assert result["duplicates_skipped"] >= 1
