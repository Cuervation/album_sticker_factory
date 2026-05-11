import csv
import re
import shutil
from pathlib import Path

from agents.curator_agent import CuratorAgent
from core import db

ALLOWED_CATEGORIES = {
    "fundacion",
    "estadio",
    "equipo",
    "jugador",
    "idolo",
    "tecnico",
    "partido",
    "campeonato",
    "copa",
    "gol",
    "festejo",
    "camiseta",
    "hinchada",
    "vuelta_boedo",
    "otro_deporte",
    "mitica",
    "archivo_historico",
}
ALLOWED_RARITIES = {"comun", "especial", "rara", "epica", "legendaria"}
ALLOWED_PRIORITIES = {"alta", "media", "baja"}


def _setup_tmp_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    chapters = tmp_path / "chapters.csv"
    seed = tmp_path / "curation_seed.json"
    targets = tmp_path / "sticker_targets.csv"
    sqlite_path = tmp_path / "stickers.sqlite"
    shutil.copy(Path("data/chapters.csv"), chapters)
    shutil.copy(Path("data/curation_seed.json"), seed)
    return chapters, seed, targets, sqlite_path


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_curator_generates_600_targets_and_valid_rows(tmp_path: Path) -> None:
    chapters, seed, targets, sqlite_path = _setup_tmp_inputs(tmp_path)
    agent = CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=targets,
        db_path=sqlite_path,
    )
    result = agent.run()
    rows = _read_rows(targets)

    assert result["generated_count"] == 600
    assert len(rows) == 600
    assert all(row["status"] == "planned" for row in rows)

    ids = [row["sticker_id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert all(re.match(r"^SL-\d{2}-\d{3}$", sid) for sid in ids)

    critical = [
        "sticker_id",
        "chapter_id",
        "chapter_title",
        "chapter_slug",
        "category",
        "target_name",
        "rarity",
        "priority",
        "search_hint",
        "status",
    ]
    for row in rows:
        for field in critical:
            assert row[field].strip() != ""
        assert row["category"] in ALLOWED_CATEGORIES
        assert row["rarity"] in ALLOWED_RARITIES
        assert row["priority"] in ALLOWED_PRIORITIES
        assert ("San Lorenzo" in row["search_hint"]) or (
            "San Lorenzo de Almagro" in row["search_hint"]
        )


def test_curator_distribution_and_idempotency(tmp_path: Path) -> None:
    chapters, seed, targets, sqlite_path = _setup_tmp_inputs(tmp_path)
    agent = CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=targets,
        db_path=sqlite_path,
    )
    agent.run()
    agent.run()

    chapter_rows = _read_rows(chapters)
    target_rows = _read_rows(targets)

    expected = {row["chapter_id"]: int(row["target_count"]) for row in chapter_rows}
    got: dict[str, int] = {}
    for row in target_rows:
        got[row["chapter_id"]] = got.get(row["chapter_id"], 0) + 1
    assert got == expected


def test_sqlite_stickers_count_after_plan_is_idempotent(tmp_path: Path) -> None:
    chapters, seed, targets, sqlite_path = _setup_tmp_inputs(tmp_path)
    agent = CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=targets,
        db_path=sqlite_path,
    )
    agent.run()
    agent.run()

    conn = db.get_connection(sqlite_path)
    try:
        assert db.count_rows(conn, "stickers") == 600
        chapter_counts = db.get_sticker_counts_by_chapter(conn)
    finally:
        conn.close()

    with chapters.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    expected = {row["chapter_id"]: int(row["target_count"]) for row in rows}
    assert chapter_counts == expected


def test_curator_can_generate_requested_total(tmp_path: Path) -> None:
    chapters, seed, targets, sqlite_path = _setup_tmp_inputs(tmp_path)
    agent = CuratorAgent(
        chapters_csv_path=chapters,
        seed_path=seed,
        targets_csv_path=targets,
        db_path=sqlite_path,
    )
    result = agent.run({"requested_total": 100})
    rows = _read_rows(targets)

    assert result["generated_count"] == 100
    assert len(rows) == 100
    assert sum(result["chapter_counts"].values()) == 100
