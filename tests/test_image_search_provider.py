from providers.image_search_provider import ImageSearchProvider


def _payload() -> dict:
    return {
        "allow_internet": True,
        "original_query": "San Lorenzo Libertadores 2014 Ortigoza foto",
        "max_results": 5,
        "max_query_variants": 3,
        "search_engines": {
            "enabled_order": ["google", "bing", "openverse"],
            "stop_after_first_engine_with_results": True,
            "providers": {
                "google": {"enabled": True, "kind": "google_images"},
                "bing": {"enabled": True, "kind": "bing_images"},
                "openverse": {"enabled": True, "kind": "openverse"},
            },
        },
    }


def test_image_search_provider_uses_google_first_and_stops(monkeypatch) -> None:
    provider = ImageSearchProvider()
    calls: list[str] = []

    def fake_search_engine(**kwargs):  # noqa: ANN003
        calls.append(str(kwargs["engine_name"]))
        return {
            "status": "ok",
            "candidates": [
                {
                    "source_page": "https://example.com/",
                    "image_url": "https://example.com/san-lorenzo.jpg",
                    "mime": "image/jpeg",
                    "width": None,
                    "height": None,
                    "license_status": "needs_manual_review",
                    "author": "",
                    "relevance_score": 0.9,
                    "executed_query": kwargs["query"],
                    "search_engine": kwargs["engine_name"],
                }
            ],
            "raw_results_seen": True,
        }

    monkeypatch.setattr(provider, "search_engine", fake_search_engine)
    result = provider.run(_payload())

    assert result["status"] == "ok"
    assert result["candidates"][0]["image_url"] == "https://example.com/san-lorenzo.jpg"
    assert result["candidates"][0]["search_engine"] == "google"
    assert calls == ["google"]


def test_image_search_provider_falls_back_to_next_engine(monkeypatch) -> None:
    provider = ImageSearchProvider()
    calls: list[str] = []

    def fake_search_engine(**kwargs):  # noqa: ANN003
        calls.append(str(kwargs["engine_name"]))
        if kwargs["engine_name"] == "google":
            return {"status": "ok", "candidates": [], "raw_results_seen": True}
        return {
            "status": "ok",
            "candidates": [
                {
                    "source_page": "https://example.org/",
                    "image_url": "https://example.org/fallback.png",
                    "mime": "image/png",
                    "width": None,
                    "height": None,
                    "license_status": "needs_manual_review",
                    "author": "",
                    "relevance_score": 0.7,
                    "executed_query": kwargs["query"],
                    "search_engine": kwargs["engine_name"],
                }
            ],
            "raw_results_seen": True,
        }

    monkeypatch.setattr(provider, "search_engine", fake_search_engine)
    result = provider.run(_payload())

    assert result["candidates"][0]["search_engine"] == "bing"
    assert calls == ["google", "bing"]


def test_parse_google_image_html_extracts_original_url() -> None:
    provider = ImageSearchProvider()
    html = r'{"ou":"https:\/\/upload.wikimedia.org\/san_lorenzo.jpg","pt":"San Lorenzo"}'

    candidates = provider.parse_html_candidates(
        html_text=html,
        query="San Lorenzo foto",
        engine_name="google",
        engine_cfg={"kind": "google_images"},
        max_results=5,
        executed_query="San Lorenzo foto",
    )

    assert len(candidates) == 1
    assert candidates[0]["image_url"] == "https://upload.wikimedia.org/san_lorenzo.jpg"
    assert candidates[0]["search_engine"] == "google"


def test_custom_html_engine_can_be_configured_with_regex() -> None:
    provider = ImageSearchProvider()
    html = r'window.__DATA__={"imageUrl":"https:\/\/cdn.example.com\/casla.webp"}'

    candidates = provider.parse_html_candidates(
        html_text=html,
        query="San Lorenzo camiseta",
        engine_name="custom",
        engine_cfg={
            "kind": "html_image_search",
            "image_url_patterns": [r'"imageUrl":"(?P<url>https?:\\/\\/[^"]+)"'],
        },
        max_results=5,
        executed_query="San Lorenzo camiseta",
    )

    assert candidates[0]["image_url"] == "https://cdn.example.com/casla.webp"
