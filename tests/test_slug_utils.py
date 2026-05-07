from core.slug_utils import slugify


def test_slug_gasometro() -> None:
    assert slugify("El Viejo Gasómetro") == "el-viejo-gasometro"


def test_slug_2012_2013() -> None:
    assert (
        slugify("Del sufrimiento a la gloria 2012/2013")
        == "del-sufrimiento-a-la-gloria-2012-2013"
    )


def test_slug_has_no_accents_or_spaces() -> None:
    slug = slugify("Ídolos eternos")
    assert " " not in slug
    assert all(ord(ch) < 128 for ch in slug)

