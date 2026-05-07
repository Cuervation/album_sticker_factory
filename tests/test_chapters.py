import csv
from pathlib import Path


def test_chapters_csv_exists() -> None:
    path = Path("data/chapters.csv")
    assert path.exists()


def test_chapters_count_and_total() -> None:
    path = Path("data/chapters.csv")
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 18
    total = sum(int(row["target_count"]) for row in rows)
    assert total == 600


def test_chapter_ids_are_01_to_18() -> None:
    path = Path("data/chapters.csv")
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    expected = [f"{i:02d}" for i in range(1, 19)]
    got = [row["chapter_id"] for row in rows]
    assert got == expected

