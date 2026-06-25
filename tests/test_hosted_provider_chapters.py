from providers.bazqux import BazQuxProvider
from providers.inoreader import InoreaderProvider
from providers.miniflux import MinifluxProvider
from providers.theoldreader import TheOldReaderProvider


class _Response:
    ok = True

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _entry(chapter_url="https://example.com/chapters.json"):
    return {
        "id": "article-1",
        "podcast_chapters": {
            "url": chapter_url,
            "type": "application/json+chapters",
        },
        "enclosures": [
            {"url": "https://example.com/episode.mp3", "mime_type": "audio/mpeg"}
        ],
    }


def _prepare_utils(monkeypatch, module, seen):
    monkeypatch.setattr(
        module.utils,
        "get_chapter_source_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        module.utils,
        "get_chapters_from_db",
        lambda *_args, **_kwargs: [],
    )

    def fake_fetch(article_id, media_url, media_type, **kwargs):
        seen.update(
            {
                "article_id": article_id,
                "media_url": media_url,
                "media_type": media_type,
                **kwargs,
            }
        )
        return [{"start": 0.0, "title": "Intro", "href": None}]

    monkeypatch.setattr(module.utils, "fetch_and_store_chapters", fake_fetch)


def test_miniflux_fetches_and_scopes_hosted_article_chapters(monkeypatch):
    import providers.miniflux as module

    provider = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://reader.example", "api_key": "x"}}}
    )
    seen = {}
    _prepare_utils(monkeypatch, module, seen)
    monkeypatch.setattr(provider, "_req", lambda method, endpoint: _entry())

    chapters = provider.get_article_chapters("article-1")

    assert chapters[0]["title"] == "Intro"
    assert seen["chapter_url"] == "https://example.com/chapters.json"
    assert seen["media_url"] == "https://example.com/episode.mp3"
    assert seen["cache_key"] == provider._chapter_cache_key("article-1")


def test_inoreader_uses_individual_item_contents_for_chapters(monkeypatch):
    import providers.inoreader as module

    provider = InoreaderProvider(
        {
            "providers": {
                "inoreader": {"app_id": "id", "app_key": "key", "token": "token"}
            }
        }
    )
    seen = {}
    request = {}
    _prepare_utils(monkeypatch, module, seen)
    monkeypatch.setattr(provider, "_has_required_auth", lambda: True)

    def fake_request(method, url, **kwargs):
        request.update({"method": method, "url": url, **kwargs})
        return _Response({"items": [_entry()]})

    monkeypatch.setattr(provider, "_request", fake_request)

    provider.get_article_chapters("article-1")

    assert request["method"] == "post"
    assert request["url"].endswith("/stream/items/contents")
    assert ("i", "article-1") in request["data"]
    assert seen["cache_key"] == provider._chapter_cache_key("article-1")


def test_bazqux_uses_individual_item_contents_for_chapters(monkeypatch):
    import providers.bazqux as module

    provider = BazQuxProvider({"providers": {"bazqux": {}}})
    seen = {}
    request = {}
    _prepare_utils(monkeypatch, module, seen)
    monkeypatch.setattr(provider, "_login", lambda: True)

    def fake_post(url, **kwargs):
        request.update({"url": url, **kwargs})
        return _Response({"items": [_entry()]})

    monkeypatch.setattr(provider.session, "post", fake_post)

    provider.get_article_chapters("article-1")

    assert request["url"].endswith("/stream/items/contents")
    assert ("i", "article-1") in request["data"]
    assert seen["cache_key"] == provider._chapter_cache_key("article-1")


def test_theoldreader_uses_individual_item_contents_for_chapters(monkeypatch):
    import providers.theoldreader as module

    provider = TheOldReaderProvider({"providers": {"theoldreader": {}}})
    seen = {}
    request = {}
    _prepare_utils(monkeypatch, module, seen)
    monkeypatch.setattr(provider, "_login", lambda: True)

    def fake_post(url, **kwargs):
        request.update({"url": url, **kwargs})
        return _Response({"items": [_entry()]})

    monkeypatch.setattr(module.requests, "post", fake_post)

    provider.get_article_chapters("article-1")

    assert request["url"].endswith("/stream/items/contents")
    assert ("i", "article-1") in request["data"]
    assert seen["cache_key"] == provider._chapter_cache_key("article-1")


def test_miniflux_changed_chapter_source_uses_current_entry_metadata(monkeypatch):
    import providers.miniflux as module

    provider = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://reader.example", "api_key": "x"}}}
    )
    calls = []
    monkeypatch.setattr(
        module.utils,
        "get_chapter_source_url",
        lambda *_args, **_kwargs: "https://example.com/old.json",
    )
    monkeypatch.setattr(
        module.utils,
        "get_chapters_from_db",
        lambda *_args, **_kwargs: [{"start": 0.0, "title": "Old", "href": None}],
    )
    monkeypatch.setattr(
        provider,
        "_req",
        lambda method, endpoint: _entry("https://example.com/new.json"),
    )

    def fake_fetch(article_id, media_url, media_type, **kwargs):
        calls.append(kwargs["chapter_url"])
        if kwargs["chapter_url"].endswith("/old.json"):
            raise AssertionError("stale chapter source should not be retried first")
        return [{"start": 0.0, "title": "New", "href": None}]

    monkeypatch.setattr(module.utils, "fetch_and_store_chapters", fake_fetch)

    chapters = provider.get_article_chapters("article-1")

    assert chapters[0]["title"] == "New"
    assert calls == ["https://example.com/new.json"]


def test_miniflux_old_source_failure_falls_back_to_cached_chapters(monkeypatch):
    import providers.miniflux as module

    provider = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://reader.example", "api_key": "x"}}}
    )
    cached = [{"start": 0.0, "title": "Cached", "href": None}]
    monkeypatch.setattr(
        module.utils,
        "get_chapter_source_url",
        lambda *_args, **_kwargs: "https://example.com/old.json",
    )
    monkeypatch.setattr(
        module.utils,
        "get_chapters_from_db",
        lambda *_args, **_kwargs: cached,
    )
    monkeypatch.setattr(provider, "_req", lambda method, endpoint: None)
    monkeypatch.setattr(
        module.utils,
        "fetch_and_store_chapters",
        lambda *_args, **_kwargs: [],
    )

    assert provider.get_article_chapters("article-1") == cached


def test_miniflux_chapter_cache_keys_include_server_and_account_identity():
    first = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://one.example", "api_key": "same"}}}
    )
    second = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://two.example", "api_key": "same"}}}
    )
    other_account = MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://one.example", "api_key": "other"}}}
    )

    keys = {
        first._chapter_cache_key("42"),
        second._chapter_cache_key("42"),
        other_account._chapter_cache_key("42"),
    }

    assert len(keys) == 3
