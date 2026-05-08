"""SQLite helpers for local state."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import CHAPTERS_CSV_PATH, DB_PATH


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open SQLite connection."""
    target = Path(db_path) if db_path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """Create required tables."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chapters (
            chapter_id TEXT PRIMARY KEY,
            chapter_title TEXT NOT NULL,
            slug TEXT NOT NULL,
            target_count INTEGER NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS stickers (
            sticker_id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL,
            chapter_title TEXT NOT NULL,
            chapter_slug TEXT NOT NULL,
            category TEXT,
            target_name TEXT NOT NULL,
            rarity TEXT,
            priority TEXT,
            search_hint TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS search_queries (
            query_id TEXT PRIMARY KEY,
            sticker_id TEXT NOT NULL,
            query TEXT NOT NULL,
            provider TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS search_routes (
            route_id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL,
            sticker_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            priority INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS image_candidates (
            image_id TEXT PRIMARY KEY,
            sticker_id TEXT NOT NULL,
            query_id TEXT,
            provider TEXT,
            source_page TEXT,
            image_url TEXT,
            local_path TEXT,
            executed_query TEXT,
            width INTEGER,
            height INTEGER,
            quality_score REAL,
            relevance_score REAL,
            duplicate_group TEXT,
            license_status TEXT,
            metadata_score REAL,
            decision_reason TEXT,
            evaluated_at TEXT,
            file_sha256 TEXT,
            file_size_bytes INTEGER,
            downloaded_at TEXT,
            download_error TEXT,
            preflight_status TEXT,
            preflight_error TEXT,
            preflight_content_type TEXT,
            preflight_content_length INTEGER,
            preflight_checked_at TEXT,
            preflight_retry_count INTEGER,
            preflight_last_retry_at TEXT,
            retry_requested_at TEXT,
            retry_requested_reason TEXT,
            retry_forced_at TEXT,
            retry_forced_reason TEXT,
            last_retry_mode TEXT,
            status TEXT NOT NULL DEFAULT 'found',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            image_id TEXT NOT NULL,
            review_status TEXT NOT NULL,
            notes TEXT,
            reviewed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            summary_json TEXT
        );
        """
    )
    _ensure_column(conn, "image_candidates", "executed_query", "TEXT")
    _ensure_column(conn, "image_candidates", "metadata_score", "REAL")
    _ensure_column(conn, "image_candidates", "decision_reason", "TEXT")
    _ensure_column(conn, "image_candidates", "evaluated_at", "TEXT")
    _ensure_column(conn, "image_candidates", "file_sha256", "TEXT")
    _ensure_column(conn, "image_candidates", "file_size_bytes", "INTEGER")
    _ensure_column(conn, "image_candidates", "downloaded_at", "TEXT")
    _ensure_column(conn, "image_candidates", "download_error", "TEXT")
    _ensure_column(conn, "image_candidates", "preflight_status", "TEXT")
    _ensure_column(conn, "image_candidates", "preflight_error", "TEXT")
    _ensure_column(conn, "image_candidates", "preflight_content_type", "TEXT")
    _ensure_column(conn, "image_candidates", "preflight_content_length", "INTEGER")
    _ensure_column(conn, "image_candidates", "preflight_checked_at", "TEXT")
    _ensure_column(conn, "image_candidates", "preflight_retry_count", "INTEGER")
    _ensure_column(conn, "image_candidates", "preflight_last_retry_at", "TEXT")
    _ensure_column(conn, "image_candidates", "retry_requested_at", "TEXT")
    _ensure_column(conn, "image_candidates", "retry_requested_reason", "TEXT")
    _ensure_column(conn, "image_candidates", "retry_forced_at", "TEXT")
    _ensure_column(conn, "image_candidates", "retry_forced_reason", "TEXT")
    _ensure_column(conn, "image_candidates", "last_retry_mode", "TEXT")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    """Add a missing column for backward-compatible schema evolution."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def load_chapters_from_csv(conn: sqlite3.Connection, csv_path: Path | str | None = None) -> int:
    """Upsert chapters from CSV and return number of rows processed."""
    source = Path(csv_path) if csv_path else CHAPTERS_CSV_PATH
    if not source.exists():
        raise FileNotFoundError(f"chapters CSV not found: {source}")

    with source.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        conn.execute(
            """
            INSERT INTO chapters (chapter_id, chapter_title, slug, target_count, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chapter_id) DO UPDATE SET
                chapter_title = excluded.chapter_title,
                slug = excluded.slug,
                target_count = excluded.target_count,
                notes = excluded.notes
            """,
            (
                row["chapter_id"],
                row["chapter_title"],
                row["slug"],
                int(row["target_count"]),
                row.get("notes", ""),
            ),
        )

    conn.commit()
    return len(rows)


def count_rows(conn: sqlite3.Connection, table_name: str) -> int:
    """Return table row count."""
    query = f"SELECT COUNT(*) AS c FROM {table_name}"
    row = conn.execute(query).fetchone()
    return int(row["c"])


def list_chapters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List chapters ordered by id."""
    rows = conn.execute(
        """
        SELECT chapter_id, chapter_title, slug, target_count, notes
        FROM chapters
        ORDER BY chapter_id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def sum_chapter_targets(conn: sqlite3.Connection) -> int:
    """Return sum(target_count) from chapters."""
    row = conn.execute("SELECT COALESCE(SUM(target_count), 0) AS total FROM chapters").fetchone()
    return int(row["total"])


def validate_target_total(conn: sqlite3.Connection, expected_total: int = 600) -> bool:
    """Validate chapter target total."""
    return sum_chapter_targets(conn) == expected_total


def validate_chapter_count(conn: sqlite3.Connection, expected_count: int = 18) -> bool:
    """Validate number of chapters."""
    return count_rows(conn, "chapters") == expected_count


def _group_status_counts(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT status, COUNT(*) AS c FROM {table} GROUP BY status ORDER BY status"
    ).fetchall()
    return {str(r["status"]): int(r["c"]) for r in rows}


def get_status_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return aggregated counters for CLI status."""
    return {
        "chapters_count": count_rows(conn, "chapters"),
        "target_total": sum_chapter_targets(conn),
        "stickers_count": count_rows(conn, "stickers"),
        "queries_count": count_rows(conn, "search_queries"),
        "routes_count": count_rows(conn, "search_routes"),
        "image_candidates_count": count_rows(conn, "image_candidates"),
        "stickers_by_status": _group_status_counts(conn, "stickers"),
        "queries_by_status": _group_status_counts(conn, "search_queries"),
        "routes_by_status": _group_status_counts(conn, "search_routes"),
        "routes_by_provider": get_route_counts_by_provider(conn),
        "image_candidates_by_provider": get_image_candidate_counts_by_provider(conn),
        "images_by_status": _group_status_counts(conn, "image_candidates"),
        "image_metadata_score_by_provider": get_image_metadata_score_by_provider(conn),
        "reviews_count": count_rows(conn, "reviews"),
        "reviews_by_status": get_reviews_by_status(conn),
        "image_candidates_with_local_path": count_image_candidates_with_local_path(conn),
        "image_candidates_with_download_error": count_image_candidates_with_download_error(conn),
        "preflight_by_status": get_preflight_status_counts(conn),
        "preflight_retry_count_total": get_preflight_retry_count_total(conn),
        "preflight_retry_candidates": count_candidates_with_preflight_retries(conn),
        "retry_requested_candidates": count_candidates_with_retry_requested(conn),
        "reviews_blocked_by_safety": count_reviews_blocked_by_safety(conn),
    }


def replace_stickers(conn: sqlite3.Connection, stickers: list[dict[str, Any]]) -> int:
    """Replace generated sticker plan using stable IDs."""
    if not stickers:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM stickers WHERE sticker_id LIKE 'SL-%'")
    conn.executemany(
        """
        INSERT INTO stickers (
            sticker_id,
            chapter_id,
            chapter_title,
            chapter_slug,
            category,
            target_name,
            rarity,
            priority,
            search_hint,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item["sticker_id"],
                item["chapter_id"],
                item["chapter_title"],
                item["chapter_slug"],
                item["category"],
                item["target_name"],
                item["rarity"],
                item["priority"],
                item["search_hint"],
                item["status"],
                now,
                now,
            )
            for item in stickers
        ],
    )
    conn.commit()
    return len(stickers)


def get_sticker_counts_by_chapter(conn: sqlite3.Connection) -> dict[str, int]:
    """Return planned sticker totals grouped by chapter."""
    rows = conn.execute(
        """
        SELECT chapter_id, COUNT(*) AS c
        FROM stickers
        GROUP BY chapter_id
        ORDER BY chapter_id
        """
    ).fetchall()
    return {str(row["chapter_id"]): int(row["c"]) for row in rows}


def list_stickers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List stickers in deterministic order."""
    rows = conn.execute(
        """
        SELECT
            sticker_id,
            chapter_id,
            chapter_title,
            chapter_slug,
            category,
            target_name,
            rarity,
            priority,
            search_hint,
            status
        FROM stickers
        ORDER BY chapter_id, sticker_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def replace_search_queries(conn: sqlite3.Connection, queries: list[dict[str, Any]]) -> int:
    """Replace generated local search queries for SL stickers."""
    conn.execute("DELETE FROM search_queries WHERE sticker_id LIKE 'SL-%'")
    if not queries:
        conn.commit()
        return 0

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO search_queries (
            query_id,
            sticker_id,
            query,
            provider,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item["query_id"],
                item["sticker_id"],
                item["query"],
                item.get("provider", ""),
                item["status"],
                now,
            )
            for item in queries
        ],
    )
    conn.commit()
    return len(queries)


def get_query_counts_by_sticker(conn: sqlite3.Connection) -> dict[str, int]:
    """Count queries grouped by sticker."""
    rows = conn.execute(
        """
        SELECT sticker_id, COUNT(*) AS c
        FROM search_queries
        GROUP BY sticker_id
        ORDER BY sticker_id
        """
    ).fetchall()
    return {str(row["sticker_id"]): int(row["c"]) for row in rows}


def list_search_queries_for_routing(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return query rows joined with sticker context for routing rules."""
    rows = conn.execute(
        """
        SELECT
            q.query_id,
            q.sticker_id,
            q.query,
            q.status AS query_status,
            s.chapter_id,
            s.chapter_title,
            s.chapter_slug,
            s.category,
            s.target_name
        FROM search_queries q
        JOIN stickers s ON s.sticker_id = q.sticker_id
        ORDER BY q.query_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def replace_search_routes(conn: sqlite3.Connection, routes: list[dict[str, Any]]) -> int:
    """Replace generated routing rows for query IDs from local planning flow."""
    conn.execute("DELETE FROM search_routes WHERE query_id LIKE 'Q-SL-%'")
    if not routes:
        conn.commit()
        return 0

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO search_routes (
            route_id,
            query_id,
            sticker_id,
            provider,
            priority,
            status,
            reason,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item["route_id"],
                item["query_id"],
                item["sticker_id"],
                item["provider"],
                int(item["priority"]),
                item["status"],
                item.get("reason", ""),
                now,
                now,
            )
            for item in routes
        ],
    )
    conn.commit()
    return len(routes)


def get_route_counts_by_provider(conn: sqlite3.Connection) -> dict[str, int]:
    """Count routes grouped by provider."""
    rows = conn.execute(
        """
        SELECT provider, COUNT(*) AS c
        FROM search_routes
        GROUP BY provider
        ORDER BY provider
        """
    ).fetchall()
    return {str(row["provider"]): int(row["c"]) for row in rows}


def get_route_counts_by_query(conn: sqlite3.Connection) -> dict[str, int]:
    """Count routes grouped by query."""
    rows = conn.execute(
        """
        SELECT query_id, COUNT(*) AS c
        FROM search_routes
        GROUP BY query_id
        ORDER BY query_id
        """
    ).fetchall()
    return {str(row["query_id"]): int(row["c"]) for row in rows}


def list_search_routes_with_context(
    conn: sqlite3.Connection,
    provider: str,
    statuses: tuple[str, ...] = ("pending", "skipped", "failed"),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List provider routes joined with query and sticker metadata."""
    status_placeholders = ", ".join(["?"] * len(statuses))
    limit_sql = " LIMIT ?" if limit is not None else ""
    query = f"""
        SELECT
            r.route_id,
            r.query_id,
            r.sticker_id,
            r.provider,
            r.priority,
            r.status AS route_status,
            r.reason,
            q.query,
            s.chapter_id,
            s.chapter_title,
            s.chapter_slug,
            s.category,
            s.target_name
        FROM search_routes r
        JOIN search_queries q ON q.query_id = r.query_id
        JOIN stickers s ON s.sticker_id = r.sticker_id
        WHERE r.provider = ?
          AND r.status IN ({status_placeholders})
        ORDER BY r.priority ASC, r.query_id ASC
        {limit_sql}
    """
    params: list[Any] = [provider, *statuses]
    if limit is not None:
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def upsert_image_candidates(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> int:
    """Upsert image candidates by stable image_id."""
    if not candidates:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO image_candidates (
            image_id,
            sticker_id,
            query_id,
            provider,
            source_page,
            image_url,
            local_path,
            executed_query,
            width,
            height,
            quality_score,
            relevance_score,
            duplicate_group,
            license_status,
            metadata_score,
            decision_reason,
            evaluated_at,
            file_sha256,
            file_size_bytes,
            downloaded_at,
            download_error,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_content_length,
            preflight_checked_at,
            preflight_retry_count,
            preflight_last_retry_at,
            retry_requested_at,
            retry_requested_reason,
            retry_forced_at,
            retry_forced_reason,
            last_retry_mode,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(image_id) DO UPDATE SET
            sticker_id = excluded.sticker_id,
            query_id = excluded.query_id,
            provider = excluded.provider,
            source_page = excluded.source_page,
            image_url = excluded.image_url,
            local_path = excluded.local_path,
            executed_query = excluded.executed_query,
            width = excluded.width,
            height = excluded.height,
            quality_score = excluded.quality_score,
            relevance_score = excluded.relevance_score,
            duplicate_group = excluded.duplicate_group,
            license_status = excluded.license_status,
            metadata_score = COALESCE(excluded.metadata_score, image_candidates.metadata_score),
            decision_reason = COALESCE(excluded.decision_reason, image_candidates.decision_reason),
            evaluated_at = COALESCE(excluded.evaluated_at, image_candidates.evaluated_at),
            file_sha256 = COALESCE(excluded.file_sha256, image_candidates.file_sha256),
            file_size_bytes = COALESCE(excluded.file_size_bytes, image_candidates.file_size_bytes),
            downloaded_at = COALESCE(excluded.downloaded_at, image_candidates.downloaded_at),
            download_error = COALESCE(excluded.download_error, image_candidates.download_error),
            preflight_status = COALESCE(excluded.preflight_status, image_candidates.preflight_status),
            preflight_error = COALESCE(excluded.preflight_error, image_candidates.preflight_error),
            preflight_content_type = COALESCE(excluded.preflight_content_type, image_candidates.preflight_content_type),
            preflight_content_length = COALESCE(excluded.preflight_content_length, image_candidates.preflight_content_length),
            preflight_checked_at = COALESCE(excluded.preflight_checked_at, image_candidates.preflight_checked_at),
            preflight_retry_count = COALESCE(excluded.preflight_retry_count, image_candidates.preflight_retry_count),
            preflight_last_retry_at = COALESCE(excluded.preflight_last_retry_at, image_candidates.preflight_last_retry_at),
            retry_requested_at = COALESCE(excluded.retry_requested_at, image_candidates.retry_requested_at),
            retry_requested_reason = COALESCE(excluded.retry_requested_reason, image_candidates.retry_requested_reason),
            retry_forced_at = COALESCE(excluded.retry_forced_at, image_candidates.retry_forced_at),
            retry_forced_reason = COALESCE(excluded.retry_forced_reason, image_candidates.retry_forced_reason),
            last_retry_mode = COALESCE(excluded.last_retry_mode, image_candidates.last_retry_mode),
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        [
            (
                item["image_id"],
                item["sticker_id"],
                item["query_id"],
                item["provider"],
                item.get("source_page"),
                item.get("image_url"),
                item["local_path"],
                item.get("executed_query"),
                item.get("width"),
                item.get("height"),
                item.get("quality_score"),
                item.get("relevance_score"),
                item.get("duplicate_group"),
                item.get("license_status"),
                item.get("metadata_score"),
                item.get("decision_reason"),
                item.get("evaluated_at"),
                item.get("file_sha256"),
                item.get("file_size_bytes"),
                item.get("downloaded_at"),
                item.get("download_error"),
                item.get("preflight_status"),
                item.get("preflight_error"),
                item.get("preflight_content_type"),
                item.get("preflight_content_length"),
                item.get("preflight_checked_at"),
                item.get("preflight_retry_count"),
                item.get("preflight_last_retry_at"),
                item.get("retry_requested_at"),
                item.get("retry_requested_reason"),
                item.get("retry_forced_at"),
                item.get("retry_forced_reason"),
                item.get("last_retry_mode"),
                item["status"],
                item.get("created_at", now),
                now,
            )
            for item in candidates
        ],
    )
    conn.commit()
    return len(candidates)


def update_search_routes_status(conn: sqlite3.Connection, statuses: dict[str, str]) -> int:
    """Update status for specific route ids."""
    if not statuses:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [(status, now, route_id) for route_id, status in statuses.items()]
    conn.executemany(
        """
        UPDATE search_routes
        SET status = ?, updated_at = ?
        WHERE route_id = ?
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def update_search_routes_outcome(
    conn: sqlite3.Connection, outcomes: dict[str, tuple[str, str]]
) -> int:
    """Update status/reason for route ids."""
    if not outcomes:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [(status, reason, now, route_id) for route_id, (status, reason) in outcomes.items()]
    conn.executemany(
        """
        UPDATE search_routes
        SET status = ?, reason = ?, updated_at = ?
        WHERE route_id = ?
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def list_image_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all image candidates for CSV export."""
    rows = conn.execute(
        """
        SELECT
            image_id,
            sticker_id,
            query_id,
            provider,
            source_page,
            image_url,
            local_path,
            executed_query,
            width,
            height,
            quality_score,
            relevance_score,
            duplicate_group,
            license_status,
            status,
            metadata_score,
            decision_reason,
            evaluated_at,
            file_sha256,
            file_size_bytes,
            downloaded_at,
            download_error,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_content_length,
            preflight_checked_at,
            preflight_retry_count,
            preflight_last_retry_at,
            retry_requested_at,
            retry_requested_reason,
            retry_forced_at,
            retry_forced_reason,
            last_retry_mode
        FROM image_candidates
        ORDER BY image_id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_image_candidates_for_evaluation(
    conn: sqlite3.Connection,
    provider: str | None = None,
    statuses: tuple[str, ...] = ("found", "needs_review", "technical_rejected", "semantic_rejected"),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List candidates to evaluate by metadata."""
    where_clauses = ["status IN ({})".format(", ".join(["?"] * len(statuses)))]
    params: list[Any] = list(statuses)
    if provider:
        where_clauses.append("provider = ?")
        params.append(provider)
    where_sql = " AND ".join(where_clauses)
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            image_id,
            sticker_id,
            query_id,
            provider,
            source_page,
            image_url,
            local_path,
            executed_query,
            width,
            height,
            quality_score,
            relevance_score,
            duplicate_group,
            license_status,
            status,
            metadata_score,
            decision_reason,
            evaluated_at,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_content_length,
            preflight_checked_at
        FROM image_candidates
        WHERE {where_sql}
        ORDER BY image_id ASC
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def update_image_candidate_evaluations(
    conn: sqlite3.Connection,
    updates: list[dict[str, Any]],
) -> int:
    """Apply metadata evaluation results for candidates."""
    if not updates:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            item["status"],
            item.get("metadata_score"),
            item.get("decision_reason", ""),
            item.get("evaluated_at", now),
            now,
            item["image_id"],
        )
        for item in updates
    ]
    conn.executemany(
        """
        UPDATE image_candidates
        SET
            status = ?,
            metadata_score = ?,
            decision_reason = ?,
            evaluated_at = ?,
            updated_at = ?
        WHERE image_id = ?
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def get_image_candidate_counts_by_provider(conn: sqlite3.Connection) -> dict[str, int]:
    """Count image candidates grouped by provider."""
    rows = conn.execute(
        """
        SELECT provider, COUNT(*) AS c
        FROM image_candidates
        GROUP BY provider
        ORDER BY provider
        """
    ).fetchall()
    return {str(row["provider"]): int(row["c"]) for row in rows}


def get_image_metadata_score_by_provider(conn: sqlite3.Connection) -> dict[str, float]:
    """Average metadata score grouped by provider."""
    rows = conn.execute(
        """
        SELECT provider, AVG(metadata_score) AS avg_score
        FROM image_candidates
        WHERE metadata_score IS NOT NULL
        GROUP BY provider
        ORDER BY provider
        """
    ).fetchall()
    return {str(row["provider"]): round(float(row["avg_score"]), 4) for row in rows}


def list_image_candidates_by_status(
    conn: sqlite3.Connection,
    statuses: tuple[str, ...],
    provider: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List image candidates filtered by statuses/provider."""
    status_placeholders = ", ".join(["?"] * len(statuses))
    where = [f"status IN ({status_placeholders})"]
    params: list[Any] = list(statuses)
    if provider:
        where.append("provider = ?")
        params.append(provider)
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            image_id,
            sticker_id,
            query_id,
            provider,
            source_page,
            image_url,
            local_path,
            executed_query,
            width,
            height,
            relevance_score,
            license_status,
            metadata_score,
            decision_reason,
            evaluated_at,
            file_sha256,
            file_size_bytes,
            downloaded_at,
            download_error,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_content_length,
            preflight_checked_at,
            preflight_retry_count,
            preflight_last_retry_at,
            retry_requested_at,
            retry_requested_reason,
            retry_forced_at,
            retry_forced_reason,
            last_retry_mode,
            status
        FROM image_candidates
        WHERE {" AND ".join(where)}
        ORDER BY image_id ASC
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_reviews(conn: sqlite3.Connection, reviews: list[dict[str, Any]]) -> int:
    """Upsert review rows by stable review_id."""
    if not reviews:
        return 0
    conn.executemany(
        """
        INSERT INTO reviews (
            review_id,
            image_id,
            review_status,
            notes,
            reviewed_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(review_id) DO UPDATE SET
            image_id = excluded.image_id,
            review_status = excluded.review_status,
            notes = excluded.notes,
            reviewed_at = excluded.reviewed_at
        """,
        [
            (
                item["review_id"],
                item["image_id"],
                item["review_status"],
                item.get("notes", ""),
                item["reviewed_at"],
            )
            for item in reviews
        ],
    )
    conn.commit()
    return len(reviews)


def update_candidate_statuses(conn: sqlite3.Connection, statuses: dict[str, str]) -> int:
    """Update image_candidates statuses by image_id."""
    if not statuses:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        UPDATE image_candidates
        SET status = ?, updated_at = ?
        WHERE image_id = ?
        """,
        [(status, now, image_id) for image_id, status in statuses.items()],
    )
    conn.commit()
    return len(statuses)


def list_approved_candidates_for_download(
    conn: sqlite3.Connection,
    provider: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List approved candidates joined with chapter_slug for output paths."""
    where = ["c.status = 'approved'"]
    params: list[Any] = []
    if provider:
        where.append("c.provider = ?")
        params.append(provider)
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            c.image_id,
            c.sticker_id,
            c.query_id,
            c.provider,
            c.source_page,
            c.image_url,
            c.local_path,
            c.width,
            c.height,
            c.relevance_score,
            c.license_status,
            c.status,
            c.file_sha256,
            c.file_size_bytes,
            c.downloaded_at,
            c.download_error,
            c.preflight_status,
            c.preflight_error,
            c.preflight_content_type,
            c.preflight_content_length,
            c.preflight_checked_at,
            c.preflight_retry_count,
            c.preflight_last_retry_at,
            c.retry_requested_at,
            c.retry_requested_reason,
            c.retry_forced_at,
            c.retry_forced_reason,
            c.last_retry_mode,
            s.chapter_slug
        FROM image_candidates c
        LEFT JOIN stickers s ON s.sticker_id = c.sticker_id
        WHERE {" AND ".join(where)}
        ORDER BY c.image_id ASC
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def update_candidate_download_result(
    conn: sqlite3.Connection,
    image_id: str,
    *,
    local_path: str | None = None,
    file_sha256: str | None = None,
    file_size_bytes: int | None = None,
    downloaded_at: str | None = None,
    download_error: str | None = None,
    status: str | None = None,
) -> None:
    """Update download fields for one candidate."""
    now = datetime.now(timezone.utc).isoformat()
    sets = ["updated_at = ?"]
    params: list[Any] = [now]
    if local_path is not None:
        sets.append("local_path = ?")
        params.append(local_path)
    if file_sha256 is not None:
        sets.append("file_sha256 = ?")
        params.append(file_sha256)
    if file_size_bytes is not None:
        sets.append("file_size_bytes = ?")
        params.append(file_size_bytes)
    if downloaded_at is not None:
        sets.append("downloaded_at = ?")
        params.append(downloaded_at)
    if download_error is not None:
        sets.append("download_error = ?")
        params.append(download_error)
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    params.append(image_id)
    conn.execute(f"UPDATE image_candidates SET {', '.join(sets)} WHERE image_id = ?", params)
    conn.commit()


def list_candidates_for_preflight(
    conn: sqlite3.Connection,
    statuses: tuple[str, ...] = ("needs_review", "approved"),
    provider: str | None = None,
    image_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List candidates eligible for preflight checks."""
    placeholders = ", ".join(["?"] * len(statuses))
    where = [f"status IN ({placeholders})"]
    params: list[Any] = list(statuses)
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if image_id:
        where.append("image_id = ?")
        params.append(image_id)
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            image_id,
            sticker_id,
            query_id,
            provider,
            image_url,
            status,
            decision_reason,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_content_length,
            preflight_checked_at,
            preflight_retry_count,
            preflight_last_retry_at,
            retry_requested_at,
            retry_requested_reason,
            retry_forced_at,
            retry_forced_reason,
            last_retry_mode
        FROM image_candidates
        WHERE {" AND ".join(where)}
        ORDER BY image_id ASC
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_candidates_for_retry_mark(
    conn: sqlite3.Connection,
    *,
    provider: str | None = None,
    image_id: str | None = None,
    preflight_status: str = "retryable",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List existing candidates that can receive manual retry metadata."""
    where = ["preflight_status = ?"]
    params: list[Any] = [preflight_status]
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if image_id:
        where.append("image_id = ?")
        params.append(image_id)
    limit_sql = " LIMIT ?" if limit is not None else ""
    if limit is not None:
        params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            image_id,
            sticker_id,
            query_id,
            provider,
            image_url,
            status,
            preflight_status,
            preflight_error,
            preflight_content_type,
            preflight_checked_at,
            preflight_retry_count,
            retry_requested_at,
            retry_requested_reason,
            retry_forced_at,
            retry_forced_reason,
            last_retry_mode
        FROM image_candidates
        WHERE {" AND ".join(where)}
        ORDER BY image_id ASC
        {limit_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def mark_candidates_retry_requested(
    conn: sqlite3.Connection,
    image_ids: list[str],
    *,
    reason: str,
    requested_at: str,
) -> int:
    """Record manual retry request metadata without changing candidate approval status."""
    if not image_ids:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        UPDATE image_candidates
        SET retry_requested_at = ?,
            retry_requested_reason = ?,
            last_retry_mode = 'manual',
            updated_at = ?
        WHERE image_id = ?
        """,
        [(requested_at, reason, now, image_id) for image_id in image_ids],
    )
    conn.commit()
    return len(image_ids)


def mark_candidates_retry_forced(
    conn: sqlite3.Connection,
    image_ids: list[str],
    *,
    reason: str,
    forced_at: str,
) -> int:
    """Record forced retry metadata without changing candidate approval status."""
    if not image_ids:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        UPDATE image_candidates
        SET retry_forced_at = ?,
            retry_forced_reason = ?,
            last_retry_mode = 'forced',
            updated_at = ?
        WHERE image_id = ?
        """,
        [(forced_at, reason, now, image_id) for image_id in image_ids],
    )
    conn.commit()
    return len(image_ids)


def update_candidate_preflight_result(
    conn: sqlite3.Connection,
    image_id: str,
    *,
    preflight_status: str,
    preflight_error: str = "",
    preflight_content_type: str = "",
    preflight_content_length: int | None = None,
    preflight_checked_at: str | None = None,
    preflight_retry_count: int | None = None,
    preflight_last_retry_at: str | None = None,
    candidate_status: str | None = None,
    decision_reason: str | None = None,
) -> None:
    """Update preflight fields and optional candidate status/reason."""
    now = datetime.now(timezone.utc).isoformat()
    checked_at = preflight_checked_at or now
    sets = [
        "preflight_status = ?",
        "preflight_error = ?",
        "preflight_content_type = ?",
        "preflight_content_length = ?",
        "preflight_checked_at = ?",
        "updated_at = ?",
    ]
    params: list[Any] = [
        preflight_status,
        preflight_error,
        preflight_content_type,
        preflight_content_length,
        checked_at,
        now,
    ]
    if candidate_status is not None:
        sets.append("status = ?")
        params.append(candidate_status)
    if preflight_retry_count is not None:
        sets.append("preflight_retry_count = ?")
        params.append(preflight_retry_count)
    if preflight_last_retry_at is not None:
        sets.append("preflight_last_retry_at = ?")
        params.append(preflight_last_retry_at)
    if decision_reason is not None:
        sets.append("decision_reason = ?")
        params.append(decision_reason)
    params.append(image_id)
    conn.execute(f"UPDATE image_candidates SET {', '.join(sets)} WHERE image_id = ?", params)
    conn.commit()


def get_reviews_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    """Count reviews grouped by review_status."""
    rows = conn.execute(
        """
        SELECT review_status, COUNT(*) AS c
        FROM reviews
        GROUP BY review_status
        ORDER BY review_status
        """
    ).fetchall()
    return {str(row["review_status"]): int(row["c"]) for row in rows}


def count_image_candidates_with_local_path(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM image_candidates WHERE COALESCE(local_path, '') <> ''"
    ).fetchone()
    return int(row["c"])


def count_image_candidates_with_download_error(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM image_candidates WHERE COALESCE(download_error, '') <> ''"
    ).fetchone()
    return int(row["c"])


def get_preflight_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT preflight_status, COUNT(*) AS c
        FROM image_candidates
        WHERE COALESCE(preflight_status, '') <> ''
        GROUP BY preflight_status
        ORDER BY preflight_status
        """
    ).fetchall()
    return {str(row["preflight_status"]): int(row["c"]) for row in rows}


def get_preflight_retry_count_total(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(preflight_retry_count, 0)), 0) AS c FROM image_candidates"
    ).fetchone()
    return int(row["c"])


def count_candidates_with_preflight_retries(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM image_candidates WHERE COALESCE(preflight_retry_count, 0) > 0"
    ).fetchone()
    return int(row["c"])


def count_candidates_with_retry_requested(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM image_candidates WHERE COALESCE(retry_requested_at, '') <> ''"
    ).fetchone()
    return int(row["c"])


def count_reviews_blocked_by_safety(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM reviews WHERE notes LIKE '%approval_blocked_by_%'"
    ).fetchone()
    return int(row["c"])
