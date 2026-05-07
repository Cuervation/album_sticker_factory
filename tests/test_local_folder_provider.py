from pathlib import Path

from providers.local_folder_provider import LocalFolderProvider


def test_list_image_files_filters_allowed_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "c.webp").write_bytes(b"x")
    (tmp_path / "d.txt").write_text("ignore", encoding="utf-8")

    provider = LocalFolderProvider()
    files = provider.list_image_files(
        base_dir=tmp_path,
        allowed_extensions=[".jpg", ".jpeg", ".png", ".webp"],
    )
    names = {item["filename"] for item in files}
    assert names == {"a.jpg", "b.png", "c.webp"}


def test_tokenize_normalizes_and_removes_stopwords() -> None:
    provider = LocalFolderProvider()
    tokens = provider.tokenize("San Lorenzo de Almagro Viejo Gasómetro imagen histórica")
    assert "san" not in tokens
    assert "lorenzo" not in tokens
    assert "gasometro" in tokens
    assert "historica" in tokens


def test_match_route_to_files_with_shared_tokens(tmp_path: Path) -> None:
    image = tmp_path / "san_lorenzo_libertadores_2014_ortigoza.jpg"
    image.write_bytes(b"fake")
    provider = LocalFolderProvider()
    files = provider.list_image_files(tmp_path, [".jpg", ".png"])
    matches = provider.match_route_to_files(
        route={
            "query": "San Lorenzo Libertadores 2014 Ortigoza penal final",
            "target_name": "Nestor Ortigoza y el penal de la final",
        },
        files=files,
    )
    assert len(matches) == 1
    assert matches[0]["relevance_score"] > 0
    assert "ortigoza" in matches[0]["shared_tokens"]

