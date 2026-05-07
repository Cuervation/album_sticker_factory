import csv
import re
import shutil
from pathlib import Path

from agents.curator_agent import CuratorAgent
from agents.query_builder_agent import QueryBuilderAgent
from agents.search_router_agent import SearchRouterAgent
from core import db

ALLOWED_PROVIDERS = {"local_folder", "wikimedia", "general_web", "image_search", "webpage"}


def _setup_ready_workspace(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    chapters = tmp_path / "chapters.csv"
    seed = tmp_path / "curation_seed.json"
    stickers_csv = tmp_path / "sticker_targets.csv"
    queries_csv = tmp_path / "search_queries.csv"
    routes_csv = tmp_path / "search_routes.csv"
    sqlite_path = tmp_path / "stickers.sqlite"
    shutil.copy(Path("data/chapters.csv"), chapters)
    shutil.copy(Path("data/curation_seed.json"), seed)
    CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=stickers_csv,
        db_path=sqlite_path,
    ).run()
    QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    ).run()
    return chapters, seed, stickers_csv, queries_csv, routes_csv, sqlite_path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_router_generates_routes_and_respects_limits(tmp_path: Path) -> None:
    _, _, _, _, routes_csv, sqlite_path = _setup_ready_workspace(tmp_path)
    router = SearchRouterAgent(db_path=sqlite_path, output_csv_path=routes_csv)
    result = router.run()
    rows = _read_csv(routes_csv)

    assert result["queries_count"] == 3000
    assert len(rows) == result["routes_generated"]
    assert len(rows) == result["total_routes_in_db"]
    assert all(row["status"] == "pending" for row in rows)
    assert all(row["provider"] in ALLOWED_PROVIDERS for row in rows)
    assert "local_folder" in {row["provider"] for row in rows}
    assert len({row["route_id"] for row in rows}) == len(rows)
    assert all(re.match(r"^R-Q-SL-\d{2}-\d{3}-\d{2}-[a-z-]+$", row["route_id"]) for row in rows)

    conn = db.get_connection(sqlite_path)
    try:
        per_query = db.get_route_counts_by_query(conn)
    finally:
        conn.close()
    assert len(per_query) == 3000
    assert min(per_query.values()) >= 3
    assert max(per_query.values()) <= 4


def test_router_is_idempotent(tmp_path: Path) -> None:
    _, _, _, _, routes_csv, sqlite_path = _setup_ready_workspace(tmp_path)
    router = SearchRouterAgent(db_path=sqlite_path, output_csv_path=routes_csv)
    router.run()
    router.run()

    conn = db.get_connection(sqlite_path)
    try:
        total = db.count_rows(conn, "search_routes")
        by_status = db.get_status_counts(conn)["routes_by_status"]
        by_provider = db.get_route_counts_by_provider(conn)
    finally:
        conn.close()

    rows = _read_csv(routes_csv)
    assert total == len(rows)
    assert by_status == {"pending": total}
    assert "local_folder" in by_provider


def test_router_csv_references_queries_and_stickers(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, routes_csv, sqlite_path = _setup_ready_workspace(tmp_path)
    SearchRouterAgent(db_path=sqlite_path, output_csv_path=routes_csv).run()

    sticker_ids = {row["sticker_id"] for row in _read_csv(stickers_csv)}
    query_rows = _read_csv(queries_csv)
    query_ids = {row["query_id"] for row in query_rows}
    query_to_sticker = {row["query_id"]: row["sticker_id"] for row in query_rows}

    rows = _read_csv(routes_csv)
    assert rows
    assert list(rows[0].keys()) == [
        "route_id",
        "query_id",
        "sticker_id",
        "provider",
        "priority",
        "status",
        "reason",
    ]
    for row in rows:
        assert row["query_id"] in query_ids
        assert row["sticker_id"] in sticker_ids
        assert row["sticker_id"] == query_to_sticker[row["query_id"]]
        assert row["provider"] in ALLOWED_PROVIDERS


def test_router_requires_queries(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "empty.sqlite"
    routes_csv = tmp_path / "routes.csv"
    conn = db.get_connection(sqlite_path)
    try:
        db.create_tables(conn)
    finally:
        conn.close()
    router = SearchRouterAgent(db_path=sqlite_path, output_csv_path=routes_csv)
    try:
        router.run()
    except ValueError as exc:
        assert "No search queries found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError when search_queries are missing")
