from pathlib import Path

from PIL import Image

from agents.crop_agent import CropAgent
from core import db


def _seed_downloaded_candidate(conn, raw_path: Path, image_id: str = "IMG-CROP-1") -> None:
    db.create_tables(conn)
    conn.execute(
        """
        INSERT INTO stickers (
            sticker_id, chapter_id, chapter_title, chapter_slug, category,
            target_name, rarity, priority, search_hint, status, created_at, updated_at
        ) VALUES ('SL-13-001','13','Libertadores 2014','libertadores-2014','jugador',
                  'Ortigoza','epica','alta','San Lorenzo Libertadores 2014','planned','now','now')
        """
    )
    db.upsert_image_candidates(
        conn,
        [
            {
                "image_id": image_id,
                "sticker_id": "SL-13-001",
                "query_id": "Q-SL-13-001-01",
                "provider": "wikimedia",
                "source_page": "https://commons.wikimedia.org/wiki/File:Crop.jpg",
                "image_url": "https://upload.wikimedia.org/crop.jpg",
                "local_path": str(raw_path.resolve()),
                "executed_query": "San Lorenzo",
                "width": 1600,
                "height": 900,
                "quality_score": None,
                "relevance_score": 0.9,
                "duplicate_group": None,
                "license_status": "attribution_required",
                "status": "downloaded",
            }
        ],
    )
    conn.commit()


def test_crop_ready_generates_square_sticker_and_manifest(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "db.sqlite"
    raw_dir = tmp_path / "tmp"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "raw.jpg"
    Image.new("RGB", (300, 200), "white").save(raw_path)
    conn = db.get_connection(db_path)
    try:
        _seed_downloaded_candidate(conn, raw_path)
    finally:
        conn.close()

    monkeypatch.setattr(
        "agents.crop_agent.load_config",
        lambda: {"output": {"final_size_px": 256, "format": "webp"}},
    )
    agent = CropAgent(
        db_path=db_path,
        output_csv_path=tmp_path / "stickers_manifest.csv",
        output_dir=tmp_path / "stickers",
    )
    result = agent.run(limit=5)
    assert result["cropped"] == 1
    sticker_path = tmp_path / "stickers" / "SL-13-001" / "IMG-CROP-1.webp"
    assert sticker_path.exists()
    with Image.open(sticker_path) as img:
        assert img.size == (256, 256)
    assert (tmp_path / "stickers_manifest.csv").exists()
