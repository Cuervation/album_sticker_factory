"""Build local provider routing plans from generated search queries."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core import db
from core.config import load_config
from core.paths import DB_PATH, SEARCH_ROUTES_CSV_PATH

PROVIDER_SLUGS = {
    "local_folder": "local-folder",
    "wikimedia": "wikimedia",
    "general_web": "general-web",
    "image_search": "image-search",
    "webpage": "webpage",
}

HISTORICAL_KEYWORDS = {
    "historico",
    "historica",
    "archivo",
    "antiguo",
    "antigua",
    "vieja",
    "viejo",
    "fundacion",
    "gasometro",
    "boedo",
    "decada",
    "1930",
    "1940",
    "1950",
    "1960",
    "1970",
    "1980",
}

CATEGORY_ROUTING_HINT = {"estadio", "archivo_historico", "fundacion", "camiseta", "vuelta_boedo"}


class SearchRouterAgent:
    """Routes local query records to provider stubs with deterministic rules."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        output_csv_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path or DB_PATH)
        self.output_csv_path = Path(output_csv_path or SEARCH_ROUTES_CSV_PATH)

    def run(self, payload: dict | None = None) -> dict[str, Any]:
        config = load_config()
        routing_cfg = config.get("search_routing", {})
        if not routing_cfg.get("enabled", True):
            raise ValueError("search_routing.enabled is false.")

        payload = payload or {}
        sticker_ids = payload.get("sticker_ids")
        if sticker_ids is not None and not isinstance(sticker_ids, list):
            sticker_ids = [str(sticker_ids)]

        provider_cfg: dict[str, Any] = routing_cfg.get("providers", {})
        enabled_providers = {
            name: cfg
            for name, cfg in provider_cfg.items()
            if isinstance(cfg, dict) and cfg.get("enabled", False)
        }
        if not enabled_providers:
            raise ValueError("No enabled providers found in search_routing.providers.")

        max_routes_per_query = int(routing_cfg.get("max_routes_per_query", 4))
        if max_routes_per_query <= 0:
            raise ValueError("search_routing.max_routes_per_query must be positive.")

        conn = db.get_connection(self.db_path)
        try:
            db.create_tables(conn)
            query_rows = db.list_search_queries_for_routing(conn)
            if sticker_ids:
                sticker_id_set = {str(item) for item in sticker_ids if str(item).strip()}
                query_rows = [row for row in query_rows if str(row.get("sticker_id")) in sticker_id_set]
            if not query_rows:
                raise ValueError("No search queries found. Primero ejecuta python main.py search")

            all_routes: list[dict[str, Any]] = []
            for query_row in query_rows:
                all_routes.extend(
                    self._build_routes_for_query(
                        query_row=query_row,
                        enabled_providers=enabled_providers,
                        max_routes_per_query=max_routes_per_query,
                    )
                )

            db.replace_search_routes(conn, all_routes)
            routes_by_provider = db.get_route_counts_by_provider(conn)
            routes_by_status = db.get_status_counts(conn).get("routes_by_status", {})
            total_routes = db.count_rows(conn, "search_routes")
        finally:
            conn.close()

        self._write_routes_csv(all_routes)
        return {
            "status": "ok",
            "message": "Local routing generated.",
            "queries_count": len(query_rows),
            "active_providers": sorted(enabled_providers.keys(), key=lambda x: enabled_providers[x]["priority"]),
            "routes_generated": len(all_routes),
            "total_routes_in_db": total_routes,
            "routes_by_provider": routes_by_provider,
            "routes_by_status": routes_by_status,
            "csv_path": str(self.output_csv_path),
        }

    def _build_routes_for_query(
        self,
        query_row: dict[str, Any],
        enabled_providers: dict[str, Any],
        max_routes_per_query: int,
    ) -> list[dict[str, Any]]:
        query_id = str(query_row["query_id"])
        sticker_id = str(query_row["sticker_id"])
        query = str(query_row["query"])
        category = str(query_row.get("category", ""))

        provider_reasons: dict[str, set[str]] = {}

        def add_provider(provider: str, reason: str) -> None:
            if provider not in enabled_providers:
                return
            provider_reasons.setdefault(provider, set()).add(reason)

        add_provider("general_web", "baseline")
        add_provider("image_search", "baseline")

        q_lower = query.casefold()
        if any(keyword in q_lower for keyword in HISTORICAL_KEYWORDS):
            add_provider("wikimedia", "historical_query")
            add_provider("webpage", "historical_query")

        if category in CATEGORY_ROUTING_HINT:
            add_provider("wikimedia", "category_rule")
            add_provider("webpage", "category_rule")

        if enabled_providers.get("local_folder", {}).get("enabled", False):
            add_provider("local_folder", "local_source_enabled")

        sorted_providers = sorted(
            provider_reasons.keys(),
            key=lambda provider: int(enabled_providers[provider].get("priority", 999)),
        )
        selected = sorted_providers[:max_routes_per_query]

        routes: list[dict[str, Any]] = []
        for provider in selected:
            slug = PROVIDER_SLUGS.get(provider, provider.replace("_", "-"))
            reason = ",".join(sorted(provider_reasons[provider]))
            routes.append(
                {
                    "route_id": f"R-{query_id}-{slug}",
                    "query_id": query_id,
                    "sticker_id": sticker_id,
                    "provider": provider,
                    "priority": int(enabled_providers[provider].get("priority", 999)),
                    "status": "pending",
                    "reason": reason,
                }
            )
        return routes

    def _write_routes_csv(self, routes: list[dict[str, Any]]) -> None:
        self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "route_id",
            "query_id",
            "sticker_id",
            "provider",
            "priority",
            "status",
            "reason",
        ]
        with self.output_csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(routes)
