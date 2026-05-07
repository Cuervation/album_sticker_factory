from core.provider_query_adapter import build_provider_queries


def test_adapter_generates_libertadores_variants() -> None:
    variants = build_provider_queries(
        provider="wikimedia",
        original_query="San Lorenzo de Almagro Plantel campeon de la Libertadores 2014 Libertadores 2014",
        target_name="Plantel campeon de la Libertadores 2014",
        chapter_title="Libertadores 2014",
        category="copa",
        max_variants=5,
        include_english_variants=True,
    )
    assert variants
    assert len(variants) <= 5
    assert any("Libertadores 2014" in q or "San Lorenzo 2014" in q for q in variants)


def test_adapter_generates_viejo_gasometro_variants() -> None:
    variants = build_provider_queries(
        provider="wikimedia",
        original_query="San Lorenzo de Almagro Vista exterior del Viejo Gasometro El Viejo Gasometro viejo gasometro y boedo",
        target_name="Vista exterior del Viejo Gasometro",
        chapter_title="El Viejo Gasometro",
        category="estadio",
        max_variants=5,
        include_english_variants=True,
    )
    assert len(variants) <= 5
    assert any("Gasometro" in q for q in variants)


def test_adapter_generates_los_matadores_variants() -> None:
    variants = build_provider_queries(
        provider="wikimedia",
        original_query="San Lorenzo Los Matadores 1968 plantel campeon",
        target_name="Los Matadores campeones de 1968",
        chapter_title="Los Matadores",
        category="equipo",
        max_variants=5,
        include_english_variants=True,
    )
    assert variants
    assert any("Matadores" in q or "1968" in q for q in variants)


def test_adapter_no_duplicates_no_urls_and_limit() -> None:
    variants = build_provider_queries(
        provider="wikimedia",
        original_query="San Lorenzo de Almagro San Lorenzo de Almagro",
        target_name="San Lorenzo de Almagro",
        chapter_title="San Lorenzo",
        category="archivo_historico",
        max_variants=5,
        include_english_variants=True,
    )
    assert len(variants) <= 5
    lowered = [q.casefold() for q in variants]
    assert len(lowered) == len(set(lowered))
    assert all("http://" not in q and "https://" not in q and "www." not in q for q in lowered)

