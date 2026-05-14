"""Direct Google Images year collector.

This intentionally bypasses the sticker/candidate/review pipeline. It opens
Google Images like a user would, scrolls the image tab, and downloads visible
image URLs for queries such as "San Lorenzo 1908".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests
from PIL import Image
from playwright.sync_api import sync_playwright


DEFAULT_OUTPUT_DIR = Path("output/raw/google-images")
MANIFEST_FILENAME = "manifest.jsonl"
SKIP_URL_PARTS = (
    "googlelogo",
    "favicon",
    "data:image",
)
MIN_PREVIEW_DIMENSION = 300


def safe_slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "query"


def ext_from_response(url: str, content_type: str) -> str:
    content_type = content_type.split(";", 1)[0].strip().lower()
    ext = mimetypes.guess_extension(content_type) or ""
    if ext == ".jpe":
        ext = ".jpg"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if ext == ".jpeg" else ext
    path_ext = Path(urlparse(url).path).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if path_ext == ".jpeg" else path_ext
    return ".jpg"


def visible_image_urls(page) -> list[str]:
    urls = page.evaluate(
        """() => Array.from(document.images)
            .filter(img => img.naturalWidth >= 80 && img.naturalHeight >= 80)
            .map(img => img.currentSrc || img.src)
            .filter(Boolean)
        """
    )
    out: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = str(raw_url).strip()
        lowered = url.lower()
        if not url.startswith(("http://", "https://")):
            continue
        if any(part in lowered for part in SKIP_URL_PARTS):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def google_original_urls_from_html(page) -> list[str]:
    try:
        html_text = page.content()
    except Exception as exc:
        print(f"[google-year-collector] html_read_skip reason={str(exc).splitlines()[0][:80]}", flush=True)
        return []
    patterns = [
        r'"ou"\s*:\s*"(?P<url>https?:\\/\\/[^"]+)"',
        r"imgurl=(?P<url>https?%3A%2F%2F[^&\"'>]+)",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
            raw_url = match.groupdict().get("url") or ""
            url = raw_url.replace("\\/", "/").replace("\\u003d", "=").replace("\\u0026", "&")
            for _ in range(2):
                decoded = unquote(url)
                if decoded == url:
                    break
                url = decoded
            lowered = url.lower()
            if not url.startswith(("http://", "https://")):
                continue
            if any(part in lowered for part in SKIP_URL_PARTS):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
    return out


def page_image_records(page) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """() => Array.from(document.images).map((img, index) => ({
                index,
                url: img.currentSrc || img.src || "",
                width: img.naturalWidth || 0,
                height: img.naturalHeight || 0,
                alt: img.alt || "",
            }))"""
        )
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
    return out


def preview_image_urls_from_records(
    records: list[dict[str, Any]],
    *,
    min_width: int = MIN_PREVIEW_DIMENSION,
    min_height: int = MIN_PREVIEW_DIMENSION,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for record in records:
        url = str(record.get("url") or "").strip()
        width = int(record.get("width") or 0)
        height = int(record.get("height") or 0)
        if not url.startswith(("http://", "https://")):
            continue
        if any(part in url.lower() for part in SKIP_URL_PARTS):
            continue
        if width < min_width or height < min_height:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def thumbnail_indices_from_records(
    records: list[dict[str, Any]],
    *,
    min_width: int = 80,
    min_height: int = 80,
    max_width: int = 420,
    max_height: int = 420,
) -> list[int]:
    indices: list[int] = []
    seen: set[int] = set()
    for record in records:
        try:
            index = int(record.get("index"))
        except Exception:
            continue
        width = int(record.get("width") or 0)
        height = int(record.get("height") or 0)
        url = str(record.get("url") or "").strip().lower()
        if index in seen:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        if any(part in url for part in SKIP_URL_PARTS):
            continue
        if width < min_width or height < min_height:
            continue
        if width > max_width or height > max_height:
            continue
        seen.add(index)
        indices.append(index)
    return indices


def manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_FILENAME


def load_manifest(output_dir: Path) -> dict[str, Any]:
    """Load prior download state so runs can resume safely."""
    path = manifest_path(output_dir)
    state: dict[str, Any] = {
        "downloaded_urls": set(),
        "downloaded_hashes": set(),
        "downloaded_by_year": {},
    }
    if not path.exists():
        return state
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("status") != "downloaded":
                continue
            url = str(item.get("url") or "").strip()
            digest = str(item.get("sha256") or "").strip()
            year = str(item.get("year") or "").strip()
            if url:
                state["downloaded_urls"].add(url)
            if digest:
                state["downloaded_hashes"].add(digest)
            if year:
                state["downloaded_by_year"][year] = int(state["downloaded_by_year"].get(year, 0)) + 1
    return state


def append_manifest_record(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(output_dir)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def blocked_by_google(page) -> bool:
    url = page.url.lower()
    if "/sorry/" in url:
        return True
    try:
        text = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        return False
    return "tráfico inusual" in text or "trafico inusual" in text or "unusual traffic" in text


def collect_urls_for_query(
    page,
    query: str,
    *,
    target_count: int,
    scrolls: int,
    pause_ms: int,
    preview_min_width: int = MIN_PREVIEW_DIMENSION,
    preview_min_height: int = MIN_PREVIEW_DIMENSION,
) -> list[str]:
    page.goto(
        "https://www.google.com/search?tbm=isch&q=" + quote(query),
        wait_until="domcontentloaded",
        timeout=45_000,
    )
    page.wait_for_timeout(1500)
    if blocked_by_google(page):
        print(
            "[google-year-collector] google_block=unusual_traffic "
            "action=solve_in_visible_browser_or_use_existing_chrome",
            flush=True,
        )
        return []

    urls: list[str] = []
    seen: set[str] = set()
    clicked: set[int] = set()
    max_clicks = max(target_count * 3, target_count + 10)
    click_attempts = 0
    for _ in range(max(1, scrolls)):
        records = page_image_records(page)
        for index in thumbnail_indices_from_records(records):
            if len(urls) >= target_count or click_attempts >= max_clicks:
                return urls
            if index in clicked:
                continue
            clicked.add(index)
            click_attempts += 1
            try:
                thumb = page.locator("img").nth(index)
                thumb.scroll_into_view_if_needed(timeout=2000)
                thumb.click(timeout=3000)
                page.wait_for_timeout(pause_ms)
            except Exception:
                continue

            for url in google_original_urls_from_html(page) + preview_image_urls_from_records(
                page_image_records(page),
                min_width=preview_min_width,
                min_height=preview_min_height,
            ):
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= target_count:
                    return urls

        for url in google_original_urls_from_html(page) + visible_image_urls(page):
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= target_count:
                return urls
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(pause_ms)
    return urls


def image_size(body: bytes) -> tuple[int, int] | None:
    try:
        from io import BytesIO

        with Image.open(BytesIO(body)) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None


def download_urls(
    urls: list[str],
    *,
    query: str,
    year: int,
    output_dir: Path,
    timeout: int,
    min_width: int,
    min_height: int,
    download_limit: int | None = None,
) -> int:
    query_dir = output_dir / safe_slug(query)
    query_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    manifest = load_manifest(output_dir)
    seen_urls: set[str] = set(manifest["downloaded_urls"])
    seen_hashes: set[str] = set(manifest["downloaded_hashes"])
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Referer": "https://www.google.com/",
        }
    )
    for idx, url in enumerate(urls, start=1):
        if download_limit is not None and downloaded >= download_limit:
            break
        if url in seen_urls:
            print(f"[google-year-collector] year={year} skip already_downloaded_url", flush=True)
            continue
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code != 200:
                append_manifest_record(output_dir, {"status": "skipped", "reason": f"http_{resp.status_code}", "year": year, "query": query, "url": url})
                continue
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.lower().startswith("image/"):
                append_manifest_record(output_dir, {"status": "skipped", "reason": "not_image_content_type", "year": year, "query": query, "url": url, "content_type": content_type})
                continue
            body = resp.content
            if len(body) < 1024:
                append_manifest_record(output_dir, {"status": "skipped", "reason": "too_small_bytes", "year": year, "query": query, "url": url, "bytes": len(body)})
                continue
            size = image_size(body)
            if not size:
                print(f"[google-year-collector] year={year} skip invalid_image", flush=True)
                append_manifest_record(output_dir, {"status": "skipped", "reason": "invalid_image", "year": year, "query": query, "url": url})
                continue
            width, height = size
            if width < min_width or height < min_height:
                print(
                    f"[google-year-collector] year={year} skip too_small width={width} height={height}",
                    flush=True,
                )
                append_manifest_record(output_dir, {"status": "skipped", "reason": "too_small_dimensions", "year": year, "query": query, "url": url, "width": width, "height": height})
                continue
            full_digest = hashlib.sha256(body).hexdigest()
            if full_digest in seen_hashes:
                print(f"[google-year-collector] year={year} skip duplicate_hash", flush=True)
                append_manifest_record(output_dir, {"status": "skipped", "reason": "duplicate_hash", "year": year, "query": query, "url": url, "sha256": full_digest})
                continue
            digest = full_digest[:10]
            ext = ext_from_response(url, content_type)
            path = query_dir / f"san-lorenzo-{year}-{idx:03d}-{digest}{ext}"
            if path.exists():
                seen_urls.add(url)
                seen_hashes.add(full_digest)
                continue
            path.write_bytes(body)
            seen_urls.add(url)
            seen_hashes.add(full_digest)
            downloaded += 1
            append_manifest_record(
                output_dir,
                {
                    "status": "downloaded",
                    "year": year,
                    "query": query,
                    "url": url,
                    "file": str(path),
                    "sha256": full_digest,
                    "bytes": len(body),
                    "width": width,
                    "height": height,
                    "content_type": content_type,
                },
            )
            print(
                f"[google-year-collector] year={year} downloaded={downloaded} width={width} height={height} file={path}",
                flush=True,
            )
        except Exception as exc:
            print(f"[google-year-collector] year={year} skip url_error={str(exc).splitlines()[0][:80]}", flush=True)
            append_manifest_record(output_dir, {"status": "skipped", "reason": "url_error", "year": year, "query": query, "url": url, "error": str(exc).splitlines()[0][:160]})
    return downloaded


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    total = 0
    with sync_playwright() as p:
        browser = None
        context = None
        if args.cdp_url:
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
        elif args.persistent_profile:
            context = p.chromium.launch_persistent_context(
                user_data_dir=args.persistent_profile,
                channel=args.channel,
                headless=False,
                viewport={"width": 1600, "height": 1000},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.new_page()
        else:
            browser = p.chromium.launch(
                headless=not args.headed,
                channel=args.channel if args.channel else None,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
        try:
            for year in range(args.start_year, args.end_year + 1):
                query = f"{args.query_prefix} {year}".strip()
                manifest = load_manifest(output_dir)
                already_downloaded = int(manifest["downloaded_by_year"].get(str(year), 0))
                if already_downloaded >= args.limit_per_year:
                    print(
                        f"[google-year-collector] year={year} step=skip already_downloaded={already_downloaded} target={args.limit_per_year}",
                        flush=True,
                    )
                    continue
                remaining_for_year = args.limit_per_year - already_downloaded
                print(f"[google-year-collector] year={year} query=\"{query}\" step=open-images", flush=True)
                target_urls = max(remaining_for_year, remaining_for_year * args.url_overfetch_factor)
                urls = collect_urls_for_query(page, query, target_count=target_urls, scrolls=args.scrolls, pause_ms=args.pause_ms)
                if blocked_by_google(page) and args.manual_wait_seconds > 0:
                    print(
                        f"[google-year-collector] waiting_for_manual_unblock seconds={args.manual_wait_seconds}",
                        flush=True,
                    )
                    page.wait_for_timeout(args.manual_wait_seconds * 1000)
                    urls = collect_urls_for_query(
                        page,
                        query,
                        target_count=target_urls,
                        scrolls=args.scrolls,
                        pause_ms=args.pause_ms,
                    )
                print(f"[google-year-collector] year={year} urls={len(urls)} step=download", flush=True)
                downloaded = download_urls(
                    urls,
                    query=query,
                    year=year,
                    output_dir=output_dir,
                    timeout=args.timeout,
                    min_width=args.min_width,
                    min_height=args.min_height,
                    download_limit=remaining_for_year,
                )
                total += downloaded
                print(f"[google-year-collector] year={year} downloaded_this_year={downloaded} total={total}", flush=True)
                time.sleep(args.year_pause_seconds)
        finally:
            if context and not args.keep_browser_open:
                context.close()
            elif browser and not args.keep_browser_open:
                browser.close()
    print(f"[google-year-collector] complete total={total} output_dir={output_dir}", flush=True)
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--query-prefix", default="San Lorenzo")
    parser.add_argument("--start-year", type=int, default=1908)
    parser.add_argument("--end-year", type=int, default=1908)
    parser.add_argument("--limit-per-year", type=int, default=50)
    parser.add_argument("--scrolls", type=int, default=8)
    parser.add_argument("--pause-ms", type=int, default=900)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--min-width", type=int, default=500)
    parser.add_argument("--min-height", type=int, default=500)
    parser.add_argument("--url-overfetch-factor", type=int, default=3)
    parser.add_argument("--year-pause-seconds", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--persistent-profile", default="")
    parser.add_argument("--cdp-url", default="")
    parser.add_argument("--manual-wait-seconds", type=int, default=0)
    parser.add_argument("--keep-browser-open", action="store_true")
    return parser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download visible Google Images results by year.")
    add_arguments(parser)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
