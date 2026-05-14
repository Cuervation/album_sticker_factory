from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

import main
from scripts import google_images_year_collector as collector


class FakePage:
    def __init__(self, html: str) -> None:
        self._html = html

    def content(self) -> str:
        return self._html


class FakeLocator:
    def __init__(self, page: "CollectPage", index: int) -> None:
        self.page = page
        self.index = index

    def scroll_into_view_if_needed(self, timeout: int) -> None:  # noqa: ARG002
        return None

    def click(self, timeout: int) -> None:  # noqa: ARG002
        self.page.clicked.append(self.index)
        self.page.preview_open = True


class CollectPage:
    def __init__(self) -> None:
        self.clicked: list[int] = []
        self.preview_open = False
        self.url = "https://www.google.com/search?tbm=isch&q=San Lorenzo 1908"
        self.mouse = self

    def goto(self, url: str, wait_until: str, timeout: int) -> None:  # noqa: ARG002
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:  # noqa: ARG002
        return None

    def wheel(self, x: int, y: int) -> None:  # noqa: ARG002
        return None

    def locator(self, selector: str) -> "CollectPage":  # noqa: ARG002
        return self

    def content(self) -> str:
        if self.preview_open:
            return r'{"ou":"https:\/\/cdn.example.com\/preview-large.jpg"}'
        return ""

    def nth(self, index: int) -> FakeLocator:
        return FakeLocator(self, index)

    def evaluate(self, script: str):  # noqa: ANN001
        if self.preview_open:
            return [
                {"index": 0, "url": "https://cdn.example.com/preview-large.jpg", "width": 800, "height": 800, "alt": ""},
                {"index": 1, "url": "https://cdn.example.com/thumb.jpg", "width": 200, "height": 200, "alt": ""},
            ]
        return [
            {"index": 0, "url": "https://cdn.example.com/thumb.jpg", "width": 200, "height": 200, "alt": ""},
            {"index": 1, "url": "https://cdn.example.com/thumb2.jpg", "width": 220, "height": 180, "alt": ""},
        ]


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg", status_code: int = 200) -> None:
        self.content = body
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}


class FakeSession:
    responses: dict[str, FakeResponse] = {}
    calls: list[str] = []

    def __init__(self) -> None:
        self.headers = {}

    def get(self, url: str, timeout: int) -> FakeResponse:  # noqa: ARG002
        self.calls.append(url)
        return self.responses[url]


def _image_bytes(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(180, 20, 30)).save(output, format="JPEG")
    return output.getvalue()


def _manifest_rows(path: Path) -> list[dict]:
    with (path / collector.MANIFEST_FILENAME).open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_google_html_extracts_original_urls() -> None:
    html = (
        r'{"ou":"https:\/\/cdn.example.com\/san-lorenzo-1908.jpg"}'
        r'<a href="/imgres?imgurl=https%3A%2F%2Fcdn.example.com%2Fotra.png&x=1">'
    )

    urls = collector.google_original_urls_from_html(FakePage(html))

    assert urls == [
        "https://cdn.example.com/san-lorenzo-1908.jpg",
        "https://cdn.example.com/otra.png",
    ]


def test_preview_helpers_select_large_images_and_thumbnails() -> None:
    records = [
        {"index": 0, "url": "https://cdn.example.com/thumb.jpg", "width": 200, "height": 200},
        {"index": 1, "url": "https://cdn.example.com/large.jpg", "width": 900, "height": 700},
    ]

    assert collector.thumbnail_indices_from_records(records) == [0]
    assert collector.preview_image_urls_from_records(records) == ["https://cdn.example.com/large.jpg"]


def test_collect_urls_for_query_clicks_thumbnail_and_collects_preview() -> None:
    page = CollectPage()

    urls = collector.collect_urls_for_query(
        page,
        "San Lorenzo 1908",
        target_count=1,
        scrolls=1,
        pause_ms=0,
    )

    assert page.clicked == [0]
    assert urls == ["https://cdn.example.com/preview-large.jpg"]


def test_download_skips_images_below_min_dimensions(tmp_path: Path, monkeypatch) -> None:
    url = "https://cdn.example.com/small.jpg"
    FakeSession.responses = {url: FakeResponse(_image_bytes(499, 600))}
    FakeSession.calls = []
    monkeypatch.setattr(collector.requests, "Session", FakeSession)

    downloaded = collector.download_urls(
        [url],
        query="San Lorenzo 1908",
        year=1908,
        output_dir=tmp_path,
        timeout=1,
        min_width=500,
        min_height=500,
        download_limit=10,
    )

    assert downloaded == 0
    assert not list((tmp_path / "san-lorenzo-1908").glob("*.jpg"))
    assert _manifest_rows(tmp_path)[0]["reason"] == "too_small_dimensions"


def test_download_dedupes_by_hash_and_resumes_by_manifest(tmp_path: Path, monkeypatch) -> None:
    url1 = "https://cdn.example.com/a.jpg"
    url2 = "https://cdn.example.com/b.jpg"
    body = _image_bytes(800, 800)
    FakeSession.responses = {url1: FakeResponse(body), url2: FakeResponse(body)}
    FakeSession.calls = []
    monkeypatch.setattr(collector.requests, "Session", FakeSession)

    first = collector.download_urls(
        [url1, url2],
        query="San Lorenzo 1908",
        year=1908,
        output_dir=tmp_path,
        timeout=1,
        min_width=500,
        min_height=500,
        download_limit=10,
    )
    second = collector.download_urls(
        [url1],
        query="San Lorenzo 1908",
        year=1908,
        output_dir=tmp_path,
        timeout=1,
        min_width=500,
        min_height=500,
        download_limit=10,
    )

    rows = _manifest_rows(tmp_path)
    assert first == 1
    assert second == 0
    assert [row["status"] for row in rows].count("downloaded") == 1
    assert any(row.get("reason") == "duplicate_hash" for row in rows)
    assert len(list((tmp_path / "san-lorenzo-1908").glob("*.jpg"))) == 1
    assert collector.load_manifest(tmp_path)["downloaded_by_year"]["1908"] == 1


def test_collect_google_years_is_official_cli_command() -> None:
    parser = main.build_parser()

    args = parser.parse_args(
        [
            "collect-google-years",
            "--query-prefix",
            "San Lorenzo",
            "--start-year",
            "1908",
            "--end-year",
            "1909",
            "--limit-per-year",
            "10",
        ]
    )

    assert args.command == "collect-google-years"
    assert args.query_prefix == "San Lorenzo"
    assert args.start_year == 1908
    assert args.end_year == 1909
    assert args.limit_per_year == 10
