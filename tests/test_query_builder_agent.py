import csv
import re
import shutil
from pathlib import Path

from agents.curator_agent import CuratorAgent
from agents.query_builder_agent import DISALLOWED_SITE_TOKENS, QueryBuilderAgent
from core import db


def _setup_curated_workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    chapters = tmp_path / "chapters.csv"
    seed = tmp_path / "curation_seed.json"
    stickers_csv = tmp_path / "sticker_targets.csv"
    queries_csv = tmp_path / "search_queries.csv"
    sqlite_path = tmp_path / "stickers.sqlite"
    shutil.copy(Path("data/chapters.csv"), chapters)
    shutil.copy(Path("data/curation_seed.json"), seed)
    CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=stickers_csv,
        db_path=sqlite_path,
    ).run()
    return chapters, seed, stickers_csv, queries_csv, sqlite_path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_query_builder_generates_3000_with_stable_ids(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, sqlite_path = _setup_curated_workspace(tmp_path)
    agent = QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    )
    result = agent.run()
    rows = _read_csv(queries_csv)

    assert result["stickers_count"] == 600
    assert result["queries_per_sticker"] == 5
    assert result["generated_queries"] == 3000
    assert len(rows) == 3000
    assert all(re.match(r"^Q-SL-\d{2}-\d{3}-\d{2}$", row["query_id"]) for row in rows)
    assert all(row["status"] == "pending" for row in rows)
    assert len({row["query_id"] for row in rows}) == 3000


def test_query_builder_is_idempotent_and_counts_per_sticker(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, sqlite_path = _setup_curated_workspace(tmp_path)
    agent = QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    )
    agent.run()
    agent.run()

    conn = db.get_connection(sqlite_path)
    try:
        assert db.count_rows(conn, "search_queries") == 3000
        by_sticker = db.get_query_counts_by_sticker(conn)
        statuses = db.get_status_counts(conn)["queries_by_status"]
    finally:
        conn.close()

    assert len(by_sticker) == 600
    assert set(by_sticker.values()) == {5}
    assert statuses == {"pending": 3000}


def test_query_quality_and_csv_integrity(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, sqlite_path = _setup_curated_workspace(tmp_path)
    QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    ).run()

    sticker_ids = {row["sticker_id"] for row in _read_csv(stickers_csv)}
    rows = _read_csv(queries_csv)
    assert rows
    assert list(rows[0].keys()) == [
        "query_id",
        "sticker_id",
        "chapter_id",
        "chapter_title",
        "chapter_slug",
        "target_name",
        "category",
        "query",
        "provider",
        "status",
    ]

    for row in rows:
        query = row["query"]
        assert row["sticker_id"] in sticker_ids
        assert query.strip() != ""
        lower_q = query.casefold()
        assert ("san lorenzo" in lower_q) or ("san lorenzo de almagro" in lower_q)
        assert "http://" not in lower_q
        assert "https://" not in lower_q
        assert "www." not in lower_q
        for token in DISALLOWED_SITE_TOKENS:
            assert token not in lower_q


def test_query_builder_requires_existing_stickers(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "empty.sqlite"
    queries_csv = tmp_path / "search_queries.csv"
    agent = QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=tmp_path / "missing_stickers.csv",
        output_csv_path=queries_csv,
    )
    try:
        agent.run()
    except ValueError as exc:
        assert "No stickers found" in str(exc)
    else:  # pragma: no cover - safety guard
        raise AssertionError("Expected ValueError when no stickers exist")


def test_query_builder_can_target_specific_stickers(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, sqlite_path = _setup_curated_workspace(tmp_path)
    sticker_rows = _read_csv(stickers_csv)
    target_ids = [sticker_rows[0]["sticker_id"], sticker_rows[1]["sticker_id"]]
    agent = QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    )
    result = agent.run({"sticker_ids": target_ids})
    rows = _read_csv(queries_csv)

    assert result["stickers_count"] == 2
    assert result["generated_queries"] == 10
    assert len(rows) == 10
    assert {row["sticker_id"] for row in rows} == set(target_ids)


def test_query_builder_chapter_mode_uses_stronger_terms(tmp_path: Path) -> None:
    _, _, stickers_csv, queries_csv, sqlite_path = _setup_curated_workspace(tmp_path)
    sticker_rows = _read_csv(stickers_csv)
    agent = QueryBuilderAgent(
        db_path=sqlite_path,
        stickers_csv_path=stickers_csv,
        output_csv_path=queries_csv,
    )
    result = agent.run({"sticker_ids": [sticker_rows[0]["sticker_id"]], "chapter_mode": True, "max_queries": 6})
    rows = _read_csv(queries_csv)
    queries = [row["query"].casefold() for row in rows]

    assert result["generated_queries"] == 6
    assert any("cicl" in query for query in queries)
    assert any("cuerv" in query for query in queries)
    assert any("boedo" in query for query in queries)
