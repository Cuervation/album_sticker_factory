"""Curates sticker target planning and writes local outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from core import db
from core.paths import CHAPTERS_CSV_PATH, CURATION_SEED_PATH, DB_PATH, STICKER_TARGETS_CSV_PATH

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


class CuratorAgent:
    """Generates first-pass sticker targets from chapter and seed inputs."""

    def __init__(
        self,
        chapters_csv_path: Path | str | None = None,
        seed_path: Path | str | None = None,
        targets_csv_path: Path | str | None = None,
        db_path: Path | str | None = None,
    ) -> None:
        self.chapters_csv_path = Path(chapters_csv_path or CHAPTERS_CSV_PATH)
        self.seed_path = Path(seed_path or CURATION_SEED_PATH)
        self.targets_csv_path = Path(targets_csv_path or STICKER_TARGETS_CSV_PATH)
        self.db_path = Path(db_path or DB_PATH)

    def run(self, payload: dict | None = None) -> dict[str, Any]:
        chapters = self._load_chapters()
        seed = self._load_seed()
        rows = self._generate_targets(chapters, seed)
        self._write_targets_csv(rows)
        self._persist_to_db(rows)

        chapter_counts: dict[str, int] = {}
        for row in rows:
            chapter_counts[row["chapter_id"]] = chapter_counts.get(row["chapter_id"], 0) + 1

        return {
            "status": "ok",
            "message": "Sticker targets generated successfully.",
            "generated_count": len(rows),
            "chapter_counts": chapter_counts,
            "csv_path": str(self.targets_csv_path),
        }

    def _load_chapters(self) -> list[dict[str, str]]:
        if not self.chapters_csv_path.exists():
            raise FileNotFoundError(f"Missing chapters CSV: {self.chapters_csv_path}")

        with self.chapters_csv_path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

        if len(rows) != 18:
            raise ValueError(f"Expected 18 chapters, found {len(rows)}.")

        total = sum(int(row["target_count"]) for row in rows)
        if total != 600:
            raise ValueError(f"Expected target total 600, found {total}.")
        return rows

    def _load_seed(self) -> dict[str, Any]:
        if not self.seed_path.exists():
            raise FileNotFoundError(f"Missing curation seed: {self.seed_path}")
        data = json.loads(self.seed_path.read_text(encoding="utf-8"))
        chapters = data.get("chapters", {})
        if not isinstance(chapters, dict):
            raise ValueError("Invalid curation seed format: chapters must be an object.")
        return data

    def _generate_targets(
        self, chapters: list[dict[str, str]], seed_data: dict[str, Any]
    ) -> list[dict[str, str]]:
        seed_chapters = seed_data.get("chapters", {})
        generated: list[dict[str, str]] = []

        for chapter in chapters:
            chapter_id = chapter["chapter_id"]
            chapter_seed = seed_chapters.get(chapter_id)
            if not chapter_seed:
                raise ValueError(f"Missing chapter seed for chapter_id={chapter_id}.")

            target_count = int(chapter["target_count"])
            chapter_rows = self._build_chapter_rows(chapter, chapter_seed, target_count)
            if len(chapter_rows) != target_count:
                raise ValueError(
                    f"Chapter {chapter_id} expected {target_count} targets, got {len(chapter_rows)}."
                )
            generated.extend(chapter_rows)

        if len(generated) != 600:
            raise ValueError(f"Expected 600 generated targets, got {len(generated)}.")
        return generated

    def _build_chapter_rows(
        self, chapter: dict[str, str], chapter_seed: dict[str, Any], target_count: int
    ) -> list[dict[str, str]]:
        chapter_id = chapter["chapter_id"]
        chapter_title = chapter["chapter_title"]
        chapter_slug = chapter["slug"]
        era_hint = chapter_seed.get("era_hint", chapter_title)

        candidates: list[dict[str, str]] = []
        seen_names: set[str] = set()

        def add_candidate(
            target_name: str,
            category: str,
            rarity: str,
            priority: str,
        ) -> None:
            name = self._clean_text(target_name)
            if not name:
                return
            key = name.casefold()
            if key in seen_names:
                return
            normalized_category = self._safe_category(category)
            normalized_rarity = self._safe_rarity(rarity)
            normalized_priority = self._safe_priority(priority)
            search_hint = self._build_search_hint(name, chapter_title, era_hint)
            candidates.append(
                {
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "chapter_slug": chapter_slug,
                    "category": normalized_category,
                    "target_name": name,
                    "rarity": normalized_rarity,
                    "priority": normalized_priority,
                    "search_hint": search_hint,
                    "status": "planned",
                }
            )
            seen_names.add(key)

        for item in chapter_seed.get("base_targets", []):
            add_candidate(
                item.get("target_name", ""),
                item.get("category", "archivo_historico"),
                item.get("rarity", "especial"),
                item.get("priority", "media"),
            )

        for entity in chapter_seed.get("named_entities", []):
            name = self._clean_text(entity.get("name", ""))
            if not name:
                continue
            base_category = entity.get("category", "archivo_historico")
            base_rarity = entity.get("rarity", "rara")
            base_priority = entity.get("priority", "media")
            add_candidate(
                f"{name} con San Lorenzo en {chapter_title}",
                base_category,
                base_rarity,
                base_priority,
            )
            add_candidate(
                f"Retrato historico de {name} en etapa azulgrana",
                base_category,
                "rara" if base_rarity == "legendaria" else base_rarity,
                base_priority,
            )
            add_candidate(
                f"{name} en partido representativo de San Lorenzo",
                "partido" if base_category in {"jugador", "idolo", "tecnico"} else base_category,
                "especial",
                "media",
            )

        themes = chapter_seed.get("themes", [])
        templates = [
            "Archivo historico de San Lorenzo sobre {label}",
            "Postal azulgrana de {label}",
            "Escena representativa de {chapter_title}: {label}",
            "Cobertura fotografica de San Lorenzo: {label}",
            "Registro de epoca del Ciclon sobre {label}",
        ]
        for theme in themes:
            label = self._clean_text(theme.get("label", ""))
            category = theme.get("category", "archivo_historico")
            if not label:
                continue
            for template in templates:
                add_candidate(
                    template.format(label=label, chapter_title=chapter_title),
                    category,
                    "especial",
                    "media",
                )

        fallback_themes = themes or [{"label": chapter_title, "category": "archivo_historico"}]
        i = 1
        while len(candidates) < target_count:
            theme = fallback_themes[(i - 1) % len(fallback_themes)]
            label = self._clean_text(theme.get("label", chapter_title))
            category = theme.get("category", "archivo_historico")
            rarity = self._rarity_for_index(i)
            priority = self._priority_for_index(i)
            add_candidate(
                f"Archivo tematico de San Lorenzo: {label} ({i:02d})",
                category,
                rarity,
                priority,
            )
            i += 1
            if i > 1000:
                raise RuntimeError(f"Failed to generate enough unique targets for chapter {chapter_id}.")

        chapter_rows = candidates[:target_count]
        for idx, row in enumerate(chapter_rows, start=1):
            row["sticker_id"] = f"SL-{chapter_id}-{idx:03d}"
        return chapter_rows

    def _write_targets_csv(self, rows: list[dict[str, str]]) -> None:
        self.targets_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
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
        with self.targets_csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _persist_to_db(self, rows: list[dict[str, str]]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            db.load_chapters_from_csv(conn, self.chapters_csv_path)
            db.replace_stickers(conn, rows)
        finally:
            conn.close()

    def _build_search_hint(self, target_name: str, chapter_title: str, era_hint: str) -> str:
        hint = f"San Lorenzo de Almagro {target_name} {chapter_title} {era_hint}"
        return " ".join(hint.split())

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _rarity_for_index(index: int) -> str:
        cycle = [
            "comun",
            "comun",
            "especial",
            "comun",
            "especial",
            "rara",
            "comun",
            "especial",
            "comun",
            "epica",
        ]
        if index % 31 == 0:
            return "legendaria"
        return cycle[(index - 1) % len(cycle)]

    @staticmethod
    def _priority_for_index(index: int) -> str:
        if index % 7 == 0:
            return "alta"
        if index % 3 == 0:
            return "media"
        return "baja"

    @staticmethod
    def _safe_category(value: str) -> str:
        return value if value in ALLOWED_CATEGORIES else "archivo_historico"

    @staticmethod
    def _safe_rarity(value: str) -> str:
        return value if value in ALLOWED_RARITIES else "especial"

    @staticmethod
    def _safe_priority(value: str) -> str:
        return value if value in ALLOWED_PRIORITIES else "media"
