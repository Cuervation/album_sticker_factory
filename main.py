"""CLI local for album_sticker_factory."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Callable, Dict

from agents.classifier_agent import ClassifierAgent
from agents.candidate_evaluator_agent import CandidateEvaluatorAgent
from agents.candidate_preflight_agent import CandidatePreflightAgent
from agents.crop_agent import CropAgent
from agents.curator_agent import CuratorAgent
from agents.download_agent import DownloadAgent
from agents.export_agent import ExportAgent
from agents.image_extractor_agent import ImageExtractorAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.quality_agent import QualityAgent
from agents.query_builder_agent import QueryBuilderAgent
from agents.report_agent import ReportAgent
from agents.review_agent import ReviewAgent
from agents.search_executor_agent import SearchExecutorAgent
from agents.search_router_agent import SearchRouterAgent
from agents.semantic_verifier_agent import SemanticVerifierAgent
from agents.source_rights_agent import SourceRightsAgent
from core import db
from core.paths import (
    CHAPTERS_CSV_PATH,
    RUNTIME_DIRECTORIES,
    SEARCH_QUERIES_CSV_PATH,
    SEARCH_ROUTES_CSV_PATH,
    IMAGE_CANDIDATES_CSV_PATH,
    ensure_directories,
)


def _count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def cmd_init(_: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    conn = db.get_connection()
    try:
        db.create_tables(conn)
        loaded = db.load_chapters_from_csv(conn, CHAPTERS_CSV_PATH)
        chapter_count = db.count_rows(conn, "chapters")
        target_total = db.sum_chapter_targets(conn)
    finally:
        conn.close()

    print("Init complete.")
    print(f"Chapters loaded/updated from CSV: {loaded}")
    print(f"Chapters in DB: {chapter_count}")
    print(f"Total target_count: {target_total}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    if not db.DB_PATH.exists():
        print("Database not found. Run: python main.py init")
        return 0

    conn = db.get_connection()
    try:
        status = db.get_status_counts(conn)
    finally:
        conn.close()

    print("Project status:")
    print(f"- Chapters: {status['chapters_count']}")
    print(f"- Target total: {status['target_total']}")
    print(f"- Stickers: {status['stickers_count']}")
    print(f"- Search queries: {status['queries_count']}")
    print(f"- Search routes: {status['routes_count']}")
    print(f"- Image candidates: {status['image_candidates_count']}")
    print(f"- Reviews: {status.get('reviews_count', 0)}")
    print(f"- Candidates with local_path: {status.get('image_candidates_with_local_path', 0)}")
    print(f"- Candidates with download_error: {status.get('image_candidates_with_download_error', 0)}")
    print(f"- Preflight retry count total: {status.get('preflight_retry_count_total', 0)}")
    print(f"- Candidates with preflight retries: {status.get('preflight_retry_candidates', 0)}")
    print(f"- Candidates marked for retry: {status.get('retry_requested_candidates', 0)}")
    print(f"- Reviews blocked_by_safety: {status.get('reviews_blocked_by_safety', 0)}")
    if SEARCH_QUERIES_CSV_PATH.exists():
        print(f"- search_queries.csv rows: {_count_csv_rows(SEARCH_QUERIES_CSV_PATH)}")
    if SEARCH_ROUTES_CSV_PATH.exists():
        print(f"- search_routes.csv rows: {_count_csv_rows(SEARCH_ROUTES_CSV_PATH)}")
    if IMAGE_CANDIDATES_CSV_PATH.exists():
        print(f"- image_candidates.csv rows: {_count_csv_rows(IMAGE_CANDIDATES_CSV_PATH)}")

    sticker_status = status.get("stickers_by_status", {})
    query_status = status.get("queries_by_status", {})
    route_status = status.get("routes_by_status", {})
    route_provider = status.get("routes_by_provider", {})
    image_status = status.get("images_by_status", {})
    image_provider = status.get("image_candidates_by_provider", {})
    image_score_provider = status.get("image_metadata_score_by_provider", {})
    review_status = status.get("reviews_by_status", {})
    preflight_status = status.get("preflight_by_status", {})
    if sticker_status:
        print("- Stickers by status:")
        for key, value in sorted(sticker_status.items()):
            print(f"  - {key}: {value}")
    if query_status:
        print("- Search queries by status:")
        for key, value in sorted(query_status.items()):
            print(f"  - {key}: {value}")
    if route_provider:
        print("- Search routes by provider:")
        for key, value in sorted(route_provider.items()):
            print(f"  - {key}: {value}")
    if route_status:
        print("- Search routes by status:")
        for key, value in sorted(route_status.items()):
            print(f"  - {key}: {value}")
    if image_provider:
        print("- Image candidates by provider:")
        for key, value in sorted(image_provider.items()):
            print(f"  - {key}: {value}")
    if image_status:
        print("- Image candidates by status:")
        for key, value in sorted(image_status.items()):
            print(f"  - {key}: {value}")
    if image_score_provider:
        print("- Image metadata_score avg by provider:")
        for key, value in sorted(image_score_provider.items()):
            print(f"  - {key}: {value:.4f}")
    if review_status:
        print("- Reviews by status:")
        for key, value in sorted(review_status.items()):
            print(f"  - {key}: {value}")
    if preflight_status:
        print("- Preflight by status:")
        for key, value in sorted(preflight_status.items()):
            print(f"  - {key}: {value}")
    return 0


def cmd_list_chapters(_: argparse.Namespace) -> int:
    if not db.DB_PATH.exists():
        print("Database not found. Run: python main.py init")
        return 0

    conn = db.get_connection()
    try:
        chapters = db.list_chapters(conn)
    finally:
        conn.close()

    if not chapters:
        print("No chapters found. Run: python main.py init")
        return 0

    print("Official chapters:")
    for chapter in chapters:
        print(
            f"{chapter['chapter_id']} | {chapter['chapter_title']} | "
            f"{chapter['slug']} | target={chapter['target_count']}"
        )
    return 0


def cmd_plan(_: argparse.Namespace) -> int:
    if not CHAPTERS_CSV_PATH.exists():
        print(f"Missing file: {CHAPTERS_CSV_PATH}")
        return 1

    ensure_directories(RUNTIME_DIRECTORIES)
    curator = CuratorAgent()
    try:
        result = curator.run({"command": "plan"})
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Plan failed: {exc}")
        return 1

    print("Plan generated successfully.")
    print(f"Stickers generated: {result['generated_count']}")
    print("Distribution by chapter:")
    for chapter_id, count in sorted(result["chapter_counts"].items()):
        print(f"  - {chapter_id}: {count}")
    print("Total expected: 600")
    print("Warning: this step only generates search targets.")
    print("No image search or image download is executed in Prompt 2.")
    return 0


def cmd_search(_: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    builder = QueryBuilderAgent()
    try:
        result = builder.run({"command": "search"})
    except ValueError as exc:
        message = str(exc)
        if "No stickers found" in message:
            print("Primero ejecuta python main.py plan")
            return 0
        print(f"Search preparation failed: {message}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Search preparation failed: {exc}")
        return 1

    print("Local search query generation complete.")
    print(f"- Stickers read: {result['stickers_count']}")
    print(f"- Queries per sticker: {result['queries_per_sticker']}")
    print(f"- Queries generated: {result['generated_queries']}")
    print(f"- Total queries in SQLite: {result['total_queries_in_db']}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se consulto internet; solo se prepararon queries locales.")
    return 0


def cmd_route_search(_: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    router = SearchRouterAgent()
    try:
        result = router.run({"command": "route-search"})
    except ValueError as exc:
        message = str(exc)
        if "No search queries found" in message:
            print("Primero ejecuta python main.py search")
            return 0
        print(f"Route-search failed: {message}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Route-search failed: {exc}")
        return 1

    print("Local routing generation complete.")
    print(f"- Queries read: {result['queries_count']}")
    print(f"- Active providers: {', '.join(result['active_providers'])}")
    print(f"- Routes generated: {result['routes_generated']}")
    print(f"- Total routes in SQLite: {result['total_routes_in_db']}")
    print("- Routes by provider:")
    for provider, count in sorted(result["routes_by_provider"].items()):
        print(f"  - {provider}: {count}")
    print("- Routes by status:")
    for status_name, count in sorted(result["routes_by_status"].items()):
        print(f"  - {status_name}: {count}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se consulto internet; solo se preparo routing local.")
    return 0


def cmd_execute_routes(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    provider = args.provider or "local_folder"
    limit = args.limit
    executor = SearchExecutorAgent()
    try:
        result = executor.run(provider=provider, limit=limit)
    except ValueError as exc:
        message = str(exc)
        if "No search routes found" in message:
            print("Primero ejecuta python main.py route-search")
            return 0
        if "only allows provider=local_folder or provider=wikimedia" in message:
            print("En Prompt 8 solo se permite --provider local_folder o --provider wikimedia")
            return 0
        print(f"Execute-routes failed: {message}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Execute-routes failed: {exc}")
        return 1

    print("Route execution complete.")
    print(f"- Provider: {result['provider']}")
    print(f"- Routes read: {result['routes_read']}")
    print(f"- Routes executed: {result['routes_executed']}")
    print(f"- Candidates found: {result.get('candidates_created', 0)}")
    print(f"- Query variants tried: {result.get('query_variants_tried', 0)}")
    print(f"- Candidates created: {result['candidates_created']}")
    print(f"- Routes routed: {result.get('routes_routed', 0)}")
    print(f"- Routes skipped: {result.get('routes_skipped', 0)}")
    print(f"- Routes failed: {result.get('routes_failed', 0)}")
    print(f"- CSV written: {result['csv_path']}")
    if result.get("message"):
        print(f"- Note: {result['message']}")
    examples = result.get("executed_query_examples", [])
    if examples:
        print("- Executed query examples:")
        for item in examples[:5]:
            print(f"  - {item}")
    print("Warning: No se descargaron imagenes; solo se guardaron URLs candidatas.")
    return 0


def cmd_evaluate_candidates(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    provider = args.provider
    limit = args.limit
    evaluator = CandidateEvaluatorAgent()
    try:
        result = evaluator.run(provider=provider, limit=limit)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Evaluate-candidates failed: {exc}")
        return 1

    if result.get("message"):
        print(result["message"])
        return 0

    print("Candidate evaluation complete.")
    print(f"- Candidates read: {result['candidates_read']}")
    print(f"- Candidates evaluated: {result['candidates_evaluated']}")
    print(f"- needs_review: {result['needs_review']}")
    print(f"- technical_rejected: {result['technical_rejected']}")
    print(f"- semantic_rejected: {result['semantic_rejected']}")
    print(f"- kept_found: {result['kept_found']}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se descargaron imagenes; solo se evaluo metadata.")
    return 0


def cmd_download_approved(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    provider = args.provider
    limit = args.limit
    agent = DownloadAgent()
    try:
        result = agent.run(provider=provider, limit=limit)
    except ValueError as exc:
        print(f"Download-approved failed: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Download-approved failed: {exc}")
        return 1

    if result.get("message"):
        print(result["message"])
        return 0

    print("Approved download complete.")
    print(f"- Approved read: {result['approved_read']}")
    print(f"- Download attempted: {result['download_attempted']}")
    print(f"- Downloaded: {result['downloaded']}")
    print(f"- Skipped: {result['skipped']}")
    print(f"- Failed: {result['failed']}")
    print(f"- Output raw path: {result['output_dir']}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se recortaron ni exportaron stickers.")
    return 0


def cmd_preflight_candidates(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    provider = args.provider
    limit = args.limit
    agent = CandidatePreflightAgent()
    try:
        result = agent.run(provider=provider, limit=limit)
    except Exception as exc:  # pragma: no cover
        print(f"Preflight-candidates failed: {exc}")
        return 1
    if result.get("message"):
        print(result["message"])
        return 0
    print("Candidate preflight complete.")
    print(f"- Candidates read: {result['candidates_read']}")
    print(f"- Checked: {result['checked']}")
    print(f"- Passed: {result['passed']}")
    print(f"- Blocked: {result['blocked']}")
    print(f"- Retryable: {result['retryable']}")
    print(f"- Failed: {result['failed']}")
    print(f"- technical_rejected: {result['technical_rejected']}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se descargaron imagenes completas; solo preflight tecnico.")
    return 0


def cmd_retry_preflight(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    provider = args.provider
    limit = args.limit
    force = bool(getattr(args, "force", False))
    agent = CandidatePreflightAgent()
    try:
        result = agent.run(provider=provider, limit=limit, retry_only=True, force=force)
    except Exception as exc:  # pragma: no cover
        print(f"Retry-preflight failed: {exc}")
        return 1
    if result.get("message"):
        print(result["message"])
        return 0
    print("Retry preflight complete.")
    print(f"- Candidates read: {result['candidates_read']}")
    print(f"- Checked: {result['checked']}")
    print(f"- Passed: {result['passed']}")
    print(f"- Blocked: {result['blocked']}")
    print(f"- Retryable: {result['retryable']}")
    print(f"- Failed: {result['failed']}")
    print(f"- technical_rejected: {result['technical_rejected']}")
    print(f"- skipped_by_preflight_status: {result.get('skipped_by_preflight_status', 0)}")
    print(f"- skipped_by_not_selected_after_mark: {result.get('skipped_by_not_selected_after_mark', 0)}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se descargaron imagenes completas; solo reintento de preflight.")
    return 0


def cmd_mark_for_retry(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    agent = CandidatePreflightAgent()
    try:
        result = agent.mark_for_retry(
            provider=args.provider,
            image_id=args.image_id,
            limit=args.limit,
            reason=args.reason,
            preflight_status=args.status,
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:
        print(f"Mark-for-retry failed: {exc}")
        return 1
    if result.get("message"):
        print(result["message"])
    print("Mark for retry complete.")
    print(f"- Provider: {result.get('provider') or 'all'}")
    print(f"- Candidates matched: {result['candidates_matched']}")
    print(f"- Marked: {result['marked']}")
    print(f"- Dry run: {result['dry_run']}")
    print(f"- CSV written: {result['csv_path']}")
    print("Warning: No se uso internet; solo se marco retry metadata.")
    return 0


def cmd_force_retry_now(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    agent = CandidatePreflightAgent()
    try:
        result = agent.force_retry_now(
            provider=args.provider,
            image_id=args.image_id,
            limit=args.limit,
            reason=args.reason,
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:
        print(f"Force-retry-now failed: {exc}")
        return 1
    if result.get("message"):
        print(result["message"])
    print("Force retry now complete.")
    print(f"- Provider: {result.get('provider') or 'all'}")
    print(f"- Candidates matched: {result['candidates_matched']}")
    print(f"- Forced marked: {result['forced_marked']}")
    print(f"- Checked: {result['checked']}")
    print(f"- Passed: {result['passed']}")
    print(f"- Blocked: {result['blocked']}")
    print(f"- Retryable: {result['retryable']}")
    print(f"- Failed: {result['failed']}")
    print(f"- technical_rejected: {result['technical_rejected']}")
    print(f"- skipped_by_provider: {result.get('skipped_by_provider', 0)}")
    print(f"- skipped_by_candidate_status: {result.get('skipped_by_candidate_status', 0)}")
    print(f"- skipped_by_preflight_status: {result.get('skipped_by_preflight_status', 0)}")
    print(f"- skipped_by_not_selected_after_mark: {result.get('skipped_by_not_selected_after_mark', 0)}")
    print(f"- skipped_by_max_retry_attempts: {result.get('skipped_by_max_retry_attempts', 0)}")
    print(f"- skipped_by_retry_window: {result.get('skipped_by_retry_window', 0)}")
    print(f"- skipped_by_status: {result.get('skipped_by_status', 0)}")
    print(f"- skipped_by_missing_url: {result.get('skipped_by_missing_url', 0)}")
    print(f"- skipped_by_other_reason: {result.get('skipped_by_other_reason', 0)}")
    print(f"- Dry run: {result['dry_run']}")
    print(f"- CSV written: {result['csv_path']}")
    if result.get("skip_summary"):
        print(f"- Skip summary: {result['skip_summary']}")
    print("Warning: No se descargaron imagenes; solo preflight tecnico forzado.")
    return 0


def cmd_review_candidates(args: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    reviewer = ReviewAgent()
    result = reviewer.run(
        {
            "action": "review-candidates",
            "provider": args.provider,
            "limit": args.limit,
        }
    )
    if result.get("status") != "ok":
        print(f"Review-candidates failed: {result.get('message', 'unknown error')}")
        return 1
    print("Review candidates preparation complete.")
    print(f"- Candidates needs_review: {result['candidates_needs_review']}")
    print(f"- HTML generated: {result['html_path']}")
    print(f"- Decisions CSV: {result['decisions_csv_path']}")
    print(f"- Existing decisions preserved: {result['decisions_existing']}")
    print(f"- New candidates added: {result['decisions_added']}")
    print("Warning: No se descargaron imagenes; solo se preparo revision manual.")
    return 0


def cmd_apply_reviews(_: argparse.Namespace) -> int:
    ensure_directories(RUNTIME_DIRECTORIES)
    reviewer = ReviewAgent()
    result = reviewer.run({"action": "apply-reviews"})
    if result.get("status") != "ok":
        print(f"Apply-reviews failed: {result.get('message', 'unknown error')}")
        return 1
    if result.get("message"):
        print(result["message"])
        return 0
    print("Manual reviews applied.")
    print(f"- Rows read: {result['rows_read']}")
    print(f"- approved applied: {result['approved_applied']}")
    print(f"- force_approved applied: {result.get('force_approved_applied', 0)}")
    print(f"- rejected applied: {result['rejected_applied']}")
    print(f"- needs_more_info applied: {result['needs_more_info_applied']}")
    print(f"- unchanged: {result['unchanged']}")
    print(f"- blocked_by_safety: {result.get('blocked_by_safety', 0)}")
    print(f"- invalid rows: {result['invalid_rows']}")
    return 0


def _run_stub_agent(agent_cls: type, command_name: str) -> int:
    result = agent_cls().run({"command": command_name})
    print(f"{command_name}: {result.get('message', 'not implemented yet')}")
    return 0


def _command_map() -> Dict[str, Callable[[argparse.Namespace], int]]:
    return {
        "init": cmd_init,
        "status": cmd_status,
        "list-chapters": cmd_list_chapters,
        "plan": cmd_plan,
        "search": cmd_search,
        "route-search": cmd_route_search,
        "execute-routes": cmd_execute_routes,
        "download": lambda _: print("Usa python main.py download-approved en esta etapa.") or 0,
        "download-approved": cmd_download_approved,
        "evaluate": cmd_evaluate_candidates,
        "evaluate-candidates": cmd_evaluate_candidates,
        "preflight-candidates": cmd_preflight_candidates,
        "retry-preflight": cmd_retry_preflight,
        "mark-for-retry": cmd_mark_for_retry,
        "force-retry-now": cmd_force_retry_now,
        "crop": lambda _: _run_stub_agent(CropAgent, "crop"),
        "classify": lambda _: _run_stub_agent(ClassifierAgent, "classify"),
        "review": cmd_review_candidates,
        "review-candidates": cmd_review_candidates,
        "apply-reviews": cmd_apply_reviews,
        "export": lambda _: _run_stub_agent(ExportAgent, "export"),
        "report": lambda _: _run_stub_agent(ReportAgent, "report"),
        "run-all": lambda _: _run_stub_agent(OrchestratorAgent, "run-all"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="album_sticker_factory local CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in _command_map().keys():
        if command in {
            "execute-routes",
            "evaluate-candidates",
            "evaluate",
            "preflight-candidates",
            "retry-preflight",
            "mark-for-retry",
            "force-retry-now",
            "review",
            "review-candidates",
            "download-approved",
        }:
            cmd = subparsers.add_parser(command)
            cmd.add_argument("--provider", default=None)
            cmd.add_argument("--limit", type=int, default=None)
            if command in {"mark-for-retry", "force-retry-now"}:
                cmd.add_argument("--image-id", default=None)
                cmd.add_argument("--reason", required=True)
                cmd.add_argument("--dry-run", action="store_true")
            if command == "retry-preflight":
                cmd.add_argument("--force", action="store_true")
            if command == "mark-for-retry":
                cmd.add_argument("--status", default="retryable")
        else:
            subparsers.add_parser(command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    commands = _command_map()
    handler = commands[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
