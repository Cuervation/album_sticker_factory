"""Provider-specific query adaptation helpers."""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(text))


def _extract_years(text: str) -> list[str]:
    return re.findall(r"(?:19|20)\d{2}", str(text or ""))


def _clean_variant(text: str) -> str:
    value = " ".join(str(text or "").split())
    value = re.sub(r"https?://\S+|www\.\S+", " ", value, flags=re.IGNORECASE)
    value = " ".join(value.split())
    return value.strip()


def build_provider_queries(
    provider: str,
    original_query: str,
    target_name: str | None,
    chapter_title: str | None,
    category: str | None,
    max_variants: int = 5,
    include_english_variants: bool = True,
) -> list[str]:
    """Build query variants for a specific provider."""
    if provider != "wikimedia":
        return [_clean_variant(original_query)] if _clean_variant(original_query) else []

    original = _clean_variant(original_query)
    target = _clean_variant(target_name or "")
    chapter = _clean_variant(chapter_title or "")
    cat = _normalize(category or "")
    years = _extract_years(f"{original} {target} {chapter}")

    variants: list[str] = []

    def add(text: str) -> None:
        candidate = _clean_variant(text)
        if not candidate:
            return
        if candidate.casefold() in {v.casefold() for v in variants}:
            return
        if re.search(r"https?://|www\.", candidate, flags=re.IGNORECASE):
            return
        variants.append(candidate)

    # Keep original first for traceability.
    add(original)

    target_tokens = _tokenize(target)
    chapter_tokens = _tokenize(chapter)
    core_tokens = [t for t in target_tokens if t not in {"san", "lorenzo", "almagro", "club", "atletico"}]
    key_phrase = " ".join(core_tokens[:4]).strip()

    if "libertadores" in _normalize(original + " " + target + " " + chapter):
        if years:
            add(f"San Lorenzo Libertadores {years[0]}")
            add(f"San Lorenzo {years[0]}")
        add("Club Atletico San Lorenzo de Almagro")
        if include_english_variants:
            add("San Lorenzo football club")

    if "gasometro" in _normalize(original + " " + target + " " + chapter):
        add("Viejo Gasometro")
        add("San Lorenzo Gasometro")
        add("Estadio Gasometro")
        add("Boedo San Lorenzo")
        if include_english_variants:
            add("San Lorenzo de Almagro stadium")

    if "matadores" in _normalize(original + " " + target + " " + chapter):
        add("San Lorenzo Los Matadores 1968")
        add("San Lorenzo Matadores")
        if include_english_variants:
            add("San Lorenzo champion team 1968")

    # Generic short variants.
    if key_phrase:
        add(f"San Lorenzo {key_phrase}")
        if years:
            add(f"San Lorenzo {key_phrase} {years[0]}")
    if chapter:
        short_chapter = " ".join(chapter_tokens[:4])
        add(f"San Lorenzo {short_chapter}")
    if years:
        add(f"San Lorenzo {years[0]}")
    add("San Lorenzo de Almagro")
    add("Club Atletico San Lorenzo de Almagro")

    if cat in {"estadio", "archivo_historico", "fundacion", "vuelta_boedo"}:
        add("San Lorenzo Boedo")
        add("San Lorenzo archivo historico")
        if include_english_variants:
            add("San Lorenzo historical archive")

    if include_english_variants and cat in {"equipo", "jugador", "idolo", "campeonato", "copa"}:
        add("San Lorenzo football")
        if years:
            add(f"San Lorenzo {years[0]} football")

    return variants[:max_variants]

