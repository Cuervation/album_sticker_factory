from urllib.error import HTTPError

from providers.wikimedia_provider import WikimediaProvider


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def test_wikimedia_provider_returns_disabled_when_internet_off(monkeypatch) -> None:
    called = {"value": False}

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        called["value"] = True
        raise AssertionError("urlopen should not be called when allow_internet is false")

    monkeypatch.setattr("providers.wikimedia_provider.urlopen", _fake_urlopen)
    provider = WikimediaProvider()
    result = provider.run({"allow_internet": False, "query": "San Lorenzo"})
    assert result["status"] == "disabled"
    assert called["value"] is False


def test_wikimedia_provider_parses_candidates_from_fake_api(monkeypatch) -> None:
    payload = """
    {
      "query": {
        "pages": {
          "1": {
            "title": "File:San Lorenzo test.jpg",
            "canonicalurl": "https://commons.wikimedia.org/wiki/File:San_Lorenzo_test.jpg",
            "imageinfo": [{
              "url": "https://upload.wikimedia.org/test.jpg",
              "descriptionurl": "https://commons.wikimedia.org/wiki/File:San_Lorenzo_test.jpg",
              "width": 1200,
              "height": 800,
              "extmetadata": {
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "John Doe"}
              }
            }]
          }
        }
      }
    }
    """

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        return _FakeResponse(payload)

    monkeypatch.setattr("providers.wikimedia_provider.urlopen", _fake_urlopen)
    provider = WikimediaProvider()
    result = provider.run(
        {
            "allow_internet": True,
            "query": "San Lorenzo Libertadores 2014",
            "max_results": 5,
            "timeout_seconds": 10,
            "user_agent": "test-agent",
        }
    )
    assert result["status"] == "ok"
    assert len(result["candidates"]) == 1
    c = result["candidates"][0]
    assert c["source_page"].startswith("https://commons.wikimedia.org/wiki/")
    assert c["image_url"].startswith("https://upload.wikimedia.org/")
    assert c["license_status"] == "attribution_required"
    assert c["executed_query"] != ""
    assert c["relevance_score"] >= 0


def test_wikimedia_provider_handles_empty_response(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        return _FakeResponse('{"query":{"pages":{}}}')

    monkeypatch.setattr("providers.wikimedia_provider.urlopen", _fake_urlopen)
    provider = WikimediaProvider()
    result = provider.run({"allow_internet": True, "query": "San Lorenzo", "max_results": 5})
    assert result["status"] == "ok"
    assert result["candidates"] == []


def test_wikimedia_provider_tries_multiple_variants_and_stops_on_success(monkeypatch) -> None:
    empty_payload = '{"query":{"pages":{}}}'
    success_payload = """
    {
      "query": {
        "pages": {
          "2": {
            "title": "File:Viejo Gasometro.jpg",
            "imageinfo": [{
              "url": "https://upload.wikimedia.org/viejo.jpg",
              "descriptionurl": "https://commons.wikimedia.org/wiki/File:Viejo_Gasometro.jpg",
              "extmetadata": {"LicenseShortName": {"value": "Public domain"}}
            }]
          }
        }
      }
    }
    """
    calls = {"n": 0}

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(empty_payload)
        return _FakeResponse(success_payload)

    monkeypatch.setattr("providers.wikimedia_provider.urlopen", _fake_urlopen)
    provider = WikimediaProvider()
    result = provider.run(
        {
            "allow_internet": True,
            "original_query": "San Lorenzo de Almagro Vista exterior del Viejo Gasometro",
            "target_name": "Vista exterior del Viejo Gasometro",
            "chapter_title": "El Viejo Gasometro",
            "category": "estadio",
            "max_query_variants": 5,
            "stop_after_first_success": True,
            "include_english_variants": True,
            "max_results": 3,
        }
    )
    assert result["status"] == "ok"
    assert calls["n"] == 2
    assert result["query_variants_tried"] == 2
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["executed_query"] == result["tried_queries"][1]


def test_wikimedia_provider_handles_http_error(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        raise HTTPError(req.full_url, 503, "service unavailable", hdrs=None, fp=None)

    monkeypatch.setattr("providers.wikimedia_provider.urlopen", _fake_urlopen)
    provider = WikimediaProvider()
    result = provider.run({"allow_internet": True, "query": "San Lorenzo"})
    assert result["status"] == "error"
    assert result["error_type"] == "http_error"
    assert result["candidates"] == []
