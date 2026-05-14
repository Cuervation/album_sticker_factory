"""Builds deterministic local search queries per sticker target."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Any

from core import db
from core.config import load_config
from core.paths import DB_PATH, SEARCH_QUERIES_CSV_PATH, STICKER_TARGETS_CSV_PATH

DISALLOWED_SITE_TOKENS = {
    "google",
    "wikipedia",
    "wikimedia",
    "pinterest",
    "facebook",
    "instagram",
    "youtube",
    "twitter",
    "x.com",
}

CATEGORY_TERMS = {
    "estadio": ["foto historica", "estadio", "tribunas", "Boedo"],
    "jugador": ["foto", "etapa azulgrana", "partido", "archivo historico"],
    "idolo": ["foto", "etapa azulgrana", "momento historico", "archivo historico"],
    "equipo": ["plantel", "formacion", "campeon", "foto"],
    "copa": ["campeon", "final", "festejo", "copa"],
    "campeonato": ["campeon", "final", "festejo", "torneo"],
    "camiseta": ["camiseta", "casaca", "indumentaria", "archivo historico"],
    "hinchada": ["hinchada", "tribuna", "bandera", "festejo"],
    "vuelta_boedo": ["Boedo vuelve", "Avenida La Plata", "regreso", "movilizacion"],
    "otro_deporte": ["disciplina", "campeon", "equipo", "competencia"],
    "mitica": ["momento historico", "imagen iconica", "archivo historico", "postal retro"],
}


class QueryBuilderAgent:
    """Generates local query variations for each planned sticker."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        stickers_csv_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.stickers_csv_path = Path(stickers_csv_path or STICKER_TARGETS_CSV_PATH)
        self.output_csv_path = Path(output_csv_path or SEARCH_QUERIES_CSV_PATH)

    def load_stickers(self, sticker_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Load stickers from SQLite, fallback to sticker_targets.csv."""
        sticker_id_set = {str(item) for item in sticker_ids or [] if str(item).strip()}
        stickers: list[dict[str, Any]] = []
        if self.db_path.exists():
            conn = db.get_connection(self.db_path)
            try:
                db.create_tables(conn)
                if sticker_id_set:
                    stickers = db.list_stickers_by_ids(conn, sorted(sticker_id_set))
                else:
                    stickers = db.list_stickers(conn)
            finally:
                conn.close()

        if sticker_id_set:
            stickers = [row for row in stickers if str(row.get("sticker_id")) in sticker_id_set]

        if stickers:
            return stickers

        if not self.stickers_csv_path.exists():
            return []

        with self.stickers_csv_path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if sticker_id_set:
            rows = [row for row in rows if str(row.get("sticker_id")) in sticker_id_set]
        return rows

    def normalize_query(self, query: str) -> str:
        """Normalize query text and enforce local policy constraints."""
        value = str(query or "")
        value = re.sub(r"https?://\S+|www\.\S+", " ", value, flags=re.IGNORECASE)
        for token in sorted(DISALLOWED_SITE_TOKENS, key=len, reverse=True):
            value = re.sub(rf"\b{re.escape(token)}\b", " ", value, flags=re.IGNORECASE)
        value = " ".join(value.replace("_", " ").split())
        if not value:
            return ""
        if "san lorenzo" not in value.lower():
            value = f"San Lorenzo {value}"
        return value

    def ensure_unique_queries(self, queries: list[str], max_queries: int) -> list[str]:
        """Deduplicate and return up to max_queries valid entries."""
        unique: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = self.normalize_query(query)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            if len(normalized) < 20:
                continue
            if re.search(r"https?://|www\.", normalized, flags=re.IGNORECASE):
                continue
            if any(token in normalized.casefold() for token in DISALLOWED_SITE_TOKENS):
                continue
            if "san lorenzo" not in normalized.casefold():
                continue
            seen.add(key)
            unique.append(normalized)
            if len(unique) >= max_queries:
                break
        return unique

    def _extract_year_candidates(self, text: str) -> list[str]:
        """Extract ordered unique year candidates from free text."""
        years: list[str] = []
        seen: set[str] = set()
        for match in re.findall(r"(?:19|20)\d{2}", str(text or "")):
            if match in seen:
                continue
            seen.add(match)
            years.append(match)
        return years

    def _build_year_sweep(self, start_year: int = 1908, end_year: int | None = None, offset: int = 0) -> list[str]:
        """Build an ordered year sweep, optionally rotated by offset."""
        final_year = int(end_year or date.today().year)
        if final_year < start_year:
            return []
        years = [str(year) for year in range(start_year, final_year + 1)]
        if not years:
            return []
        rotation = offset % len(years) if offset else 0
        if rotation:
            years = years[rotation:] + years[:rotation]
        return years

    def build_queries_for_sticker(
        self,
        sticker: dict[str, Any],
        max_queries: int,
        *,
        chapter_mode: bool = False,
        year_start: int = 1908,
        year_end: int | None = None,
        year_offset: int = 0,
    ) -> list[dict[str, str]]:
        """Build query rows for a single sticker."""
        sticker_id = str(sticker["sticker_id"])
        chapter_id = str(sticker["chapter_id"])
        chapter_title = str(sticker["chapter_title"])
        chapter_slug = str(sticker["chapter_slug"])
        target_name = str(sticker["target_name"])
        category = str(sticker["category"])
        search_hint = str(sticker.get("search_hint", "")).strip()

        chapter_focus = f"{chapter_title} {search_hint}" if chapter_mode else f"{target_name} {chapter_title} {search_hint}"
        year_candidates = self._extract_year_candidates(chapter_focus)
        year_sweep = self._build_year_sweep(start_year=year_start, end_year=year_end, offset=year_offset)
        year_hint = year_candidates[0] if year_candidates else ""
        terms = CATEGORY_TERMS.get(category, ["foto", "imagen", "archivo historico", "San Lorenzo"])

        if chapter_mode:
            raw_candidates = [
                f"San Lorenzo {chapter_title} foto",
                f"San Lorenzo de Almagro {chapter_title} archivo historico",
                f"San Lorenzo {chapter_title} imagen",
                f"San Lorenzo {chapter_title} Ciclon",
                f"San Lorenzo {chapter_title} cuervos",
                f"San Lorenzo {chapter_title} Boedo",
                f"San Lorenzo {chapter_title} {year_hint} archivo historico",
                f"San Lorenzo {chapter_title} {category} foto historica",
                f"San Lorenzo {chapter_title} {target_name}",
            ]
            for year in year_sweep:
                raw_candidates.extend(
                    [
                        f"San Lorenzo {chapter_title} {year} foto",
                        f"San Lorenzo de Almagro {chapter_title} {year} archivo historico",
                        f"San Lorenzo {chapter_title} {year} imagen",
                    ]
                )
        else:
            raw_candidates = [
                search_hint,
                f"San Lorenzo de Almagro {target_name} {chapter_title} foto",
                f"San Lorenzo {target_name} {terms[0]} {terms[1]}",
                f"San Lorenzo {chapter_title} {target_name} {terms[2]}",
                f"San Lorenzo {target_name} {terms[3]} imagen",
                f"San Lorenzo de Almagro {target_name} {year_hint} archivo historico",
                f"San Lorenzo {chapter_title} {category} {target_name} foto historica",
                f"San Lorenzo {target_name} {chapter_title} plantel partido festejo",
            ]

        queries = self.ensure_unique_queries(raw_candidates, max_queries)
        i = 1
        while len(queries) < max_queries:
            year_pool = year_sweep if year_sweep else (year_candidates if year_candidates else [year_hint])
            year_variant = year_pool[(i - 1) % len(year_pool)]
            fallback = (
                f"San Lorenzo {target_name} {chapter_title} "
                f"{year_variant} {terms[(i - 1) % len(terms)]} archivo historico {i:02d}"
            )
            fallback_normalized = self.normalize_query(fallback)
            queries = self.ensure_unique_queries(queries + [fallback_normalized], max_queries)
            i += 1
            if i > 40:
                raise RuntimeError(f"Could not generate {max_queries} unique queries for {sticker_id}.")
        query_rows: list[dict[str, str]] = []
        sticker_parts = sticker_id.split("-")
        if len(sticker_parts) != 3:
            raise ValueError(f"Invalid sticker_id format: {sticker_id}")
        cc = sticker_parts[1]
        nnn = sticker_parts[2]
        for idx, query in enumerate(queries, start=1):
            query_rows.append(
                {
                    "query_id": f"Q-SL-{cc}-{nnn}-{idx:02d}",
                    "sticker_id": sticker_id,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "chapter_slug": chapter_slug,
                    "target_name": target_name,
                    "category": category,
                    "query": query,
                    "provider": "pending",
                    "status": "pending",
                }
            )
        return query_rows

    def run(self, payload: dict | None = None) -> dict[str, Any]:
        config = load_config()
        max_queries = int(config.get("pipeline", {}).get("max_queries_per_sticker", 5))
        if max_queries <= 0:
            raise ValueError("pipeline.max_queries_per_sticker must be a positive integer.")

        payload = payload or {}
        requested_max_queries = payload.get("max_queries")
        if requested_max_queries is not None:
            max_queries = int(requested_max_queries)
            if max_queries <= 0:
                raise ValueError("payload.max_queries must be a positive integer.")
        sticker_ids = payload.get("sticker_ids")
        if sticker_ids is not None and not isinstance(sticker_ids, list):
            sticker_ids = [str(sticker_ids)]

        chapter_mode = bool(payload.get("chapter_mode", False))
        year_start = int(payload.get("year_start", 1908) or 1908)
        year_end = payload.get("year_end")
        year_end = int(year_end) if year_end is not None else None
        year_offset = int(payload.get("year_offset", 0) or 0)
        chapter_ids = payload.get("chapter_ids")
        if chapter_ids is not None and not isinstance(chapter_ids, list):
            chapter_ids = [str(chapter_ids)]

        stickers = self.load_stickers(sticker_ids=sticker_ids)
        if chapter_ids is not None:
            chapter_id_set = {str(item) for item in chapter_ids if str(item).strip()}
            if chapter_id_set:
                stickers = [row for row in stickers if str(row.get("chapter_id")) in chapter_id_set]
        if not stickers:
            if sticker_ids:
                raise ValueError("No stickers found for selected sticker_ids.")
            if chapter_ids:
                raise ValueError("No stickers found for selected chapter_ids.")
            raise ValueError("No stickers found. Primero ejecuta python main.py plan")

        all_queries: list[dict[str, str]] = []
        for sticker in stickers:
            all_queries.extend(
                self.build_queries_for_sticker(
                    sticker,
                    max_queries,
                    chapter_mode=chapter_mode,
                    year_start=year_start,
                    year_end=year_end,
                    year_offset=year_offset,
                )
            )

        expected_total = len(stickers) * max_queries
        if len(all_queries) != expected_total:
            raise ValueError(f"Expected {expected_total} queries, generated {len(all_queries)}.")

        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as fh:
            fieldnames = [
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
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_queries)

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            db.replace_search_queries(conn, all_queries)
            total_in_db = db.count_rows(conn, "search_queries")
        finally:
            conn.close()

        return {
            "status": "ok",
            "message": "Local queries generated.",
            "stickers_count": len(stickers),
            "chapter_mode": chapter_mode,
            "queries_per_sticker": max_queries,
            "generated_queries": len(all_queries),
            "total_queries_in_db": total_in_db,
            "csv_path": str(self.output_csv_path),
        }
