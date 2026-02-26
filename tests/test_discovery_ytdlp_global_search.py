from unittest.mock import patch
import sys
import types

from core import discovery


class _FakeSearchExtractor:
    _SEARCH_KEY = ""
    _WORKING = True
    IE_NAME = ""
    IE_DESC = ""
    _IE_KEY = ""

    @classmethod
    def ie_key(cls):
        return cls._IE_KEY or cls.__name__


class _YoutubeSearch(_FakeSearchExtractor):
    _SEARCH_KEY = "ytsearch"
    IE_NAME = "youtube:search"
    IE_DESC = "YouTube search"
    _IE_KEY = "YoutubeSearch"


class _NicoSearch(_FakeSearchExtractor):
    _SEARCH_KEY = "nicosearch"
    IE_NAME = "nicovideo:search"
    IE_DESC = "Nico video search"
    _IE_KEY = "NicovideoSearch"


class _NicoSearchDate(_FakeSearchExtractor):
    _SEARCH_KEY = "nicosearchdate"
    IE_NAME = "nicovideo:search:date"
    IE_DESC = "Nico video search, newest first"
    _IE_KEY = "NicovideoSearchDate"


class _AdultSearch(_FakeSearchExtractor):
    _SEARCH_KEY = "pornsearch"
    IE_NAME = "adulttube:search"
    IE_DESC = "Adult video search"
    _IE_KEY = "AdultTubeSearch"


class _NoSearchExtractor:
    @classmethod
    def ie_key(cls):
        return "Generic"


class _InheritedSearchBase:
    _SEARCH_KEY = "scsearch"
    IE_NAME = "soundcloud:search"
    IE_DESC = "Soundcloud search"
    _WORKING = True


class _InheritedSoundcloudSearchIE(_InheritedSearchBase):
    _IE_KEY = "SoundcloudSearch"

    @classmethod
    def ie_key(cls):
        return cls._IE_KEY


def test_get_ytdlp_searchable_sites_filters_adult_and_dedupes_variants():
    fake_extractors = [
        _YoutubeSearch,
        _NicoSearchDate,
        _NicoSearch,
        _AdultSearch,
        _NoSearchExtractor,
        _InheritedSoundcloudSearchIE,
    ]

    with patch("core.discovery._get_ytdlp_extractors", return_value=fake_extractors):
        safe_sites = discovery.get_ytdlp_searchable_sites(include_adult=False)
        all_sites = discovery.get_ytdlp_searchable_sites(include_adult=True)

    safe_ids = {row["id"] for row in safe_sites}
    assert "ytsearch" in safe_ids
    assert "nicosearch" in safe_ids
    assert "scsearch" in safe_ids
    assert all(not bool(row.get("adult")) for row in safe_sites)
    assert any(bool(row.get("adult")) for row in all_sites)

    nico_rows = [row for row in safe_sites if row["id"] == "nicosearch"]
    assert len(nico_rows) == 1
    assert nico_rows[0]["search_key"] == "nicosearch"
    assert nico_rows[0]["label"] == "Niconico"


def test_search_ytdlp_site_normalizes_kind_and_subscribe_urls():
    site = {"id": "ytsearch", "label": "YouTube", "search_key": "ytsearch"}
    entries = [
        {
            "title": "Video result",
            "url": "BaW_jenozKc",
            "webpage_url": "https://www.youtube.com/watch?v=BaW_jenozKc",
            "channel": "Example",
            "channel_id": "UCVID123",
            "channel_url": "https://www.youtube.com/channel/UCVID123",
            "duration": 61,
            "view_count": 123456,
        },
        {
            "title": "Playlist result",
            "_type": "playlist",
            "webpage_url": "https://www.youtube.com/playlist?list=PL123",
        },
        {
            "title": "Channel result",
            "webpage_url": "https://www.youtube.com/@examplechannel",
        },
        {
            "title": "RSS result",
            "webpage_url": "https://example.com/feed.xml",
        },
    ]

    def _fake_native(url):
        if "playlist?list=" in url:
            return "https://www.youtube.com/feeds/videos.xml?playlist_id=PL123"
        if "/channel/" in url:
            return "https://www.youtube.com/feeds/videos.xml?channel_id=UCVID123"
        if "/@" in url:
            return "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"
        return ""

    with patch("core.discovery._run_ytdlp_query_search", return_value=entries), patch(
        "core.discovery.get_ytdlp_feed_url", side_effect=_fake_native
    ), patch("core.discovery.is_ytdlp_supported", return_value=True):
        out = discovery.search_ytdlp_site("example", site, limit=10, timeout=10)

    assert len(out) == 4

    video, playlist, channel, feed = out
    assert video["url"] == "https://www.youtube.com/watch?v=BaW_jenozKc"
    assert video["kind"] == "media"
    assert video["play_count"] == 123456
    assert video["native_subscribe_url"].endswith("channel_id=UCVID123")
    assert video["source_subscribe_url"] == "https://www.youtube.com/channel/UCVID123"

    assert playlist["kind"] == "playlist"
    assert playlist["native_subscribe_url"].endswith("playlist_id=PL123")
    assert playlist["source_subscribe_url"] == "https://www.youtube.com/playlist?list=PL123"

    assert channel["kind"] == "user"
    assert channel["native_subscribe_url"].endswith("channel_id=UC123")
    assert channel["source_subscribe_url"] == "https://www.youtube.com/@examplechannel"

    assert feed["kind"] == "feed"
    assert feed["native_subscribe_url"] == "https://example.com/feed.xml"
    assert feed["source_subscribe_url"] == "https://example.com/feed.xml"


def test_soundcloud_media_results_expose_uploader_subscribe_url():
    site = {"id": "scsearch", "label": "SoundCloud", "search_key": "scsearch"}
    entries = [
        {
            "title": "Track",
            "webpage_url": "https://soundcloud.com/user/track",
            "uploader": "Artist",
            "uploader_url": "https://soundcloud.com/user",
        }
    ]

    with patch("core.discovery._run_ytdlp_query_search", return_value=entries), patch(
        "core.discovery.get_ytdlp_feed_url", return_value=""
    ), patch("core.discovery.get_social_feed_url", return_value=""):
        out = discovery.search_ytdlp_site("track", site, limit=10, timeout=10)

    assert len(out) == 1
    assert out[0]["kind"] == "media"
    assert out[0]["source_subscribe_url"] == "https://soundcloud.com/user"


def test_normalize_ytdlp_search_entries_uses_friendly_fallback_titles_for_url_only_rows():
    site = {"id": "rkfnsearch", "label": "Rokfin", "search_key": "rkfnsearch"}
    entries = [
        {"_type": "url", "url": "https://rokfin.com/stream/18601"},
        {"_type": "url", "url": "https://rokfin.com/post/56518"},
        {"_type": "url", "url": "https://www.facebook.com/reel/1619096122624930/"},
    ]

    with patch("core.discovery._resolve_quick_url_title_cached", return_value=""):
        out = discovery._normalize_ytdlp_search_entries(entries, site=site, limit=10)

    assert out[0]["title"] == "Rokfin stream 18601"
    assert out[1]["title"] == "Rokfin post 56518"
    assert out[2]["title"] == "Facebook reel 1619096122624930"
    assert all(bool(item.get("_title_is_fallback")) for item in out)


def test_normalize_ytdlp_search_entries_marks_rokfin_stack_as_playlist():
    site = {"id": "rkfnsearch", "label": "Rokfin", "search_key": "rkfnsearch"}
    entries = [{"_type": "url", "url": "https://rokfin.com/stack/1176"}]

    with patch("core.discovery._resolve_quick_url_title_cached", return_value=""):
        out = discovery._normalize_ytdlp_search_entries(entries, site=site, limit=10)

    assert len(out) == 1
    assert out[0]["kind"] == "playlist"
    assert out[0]["title"] == "Rokfin stack 1176"


def test_wrapper_search_results_use_actual_source_site_label_from_url():
    site = {"id": "yvsearch", "label": "Yahoo Video", "search_key": "yvsearch"}
    entries = [
        {"_type": "url", "url": "https://www.youtube.com/watch?v=C4W_zvyoJu8"},
        {"_type": "url", "url": "https://www.facebook.com/reel/1619096122624930/"},
    ]

    with patch("core.discovery._resolve_quick_url_title_cached", return_value=""):
        out = discovery._normalize_ytdlp_search_entries(entries, site=site, limit=10)

    assert len(out) == 2
    assert out[0]["site_id"] == "yvsearch"
    assert out[0]["site"] == "YouTube"
    assert out[0]["title"] == "YouTube video C4W_zvyoJu8"
    assert out[0]["detail"] == "YouTube"
    assert out[1]["site"] == "Facebook"
    assert out[1]["title"] == "Facebook reel 1619096122624930"
    assert out[1]["detail"] == "Facebook"


def test_normalize_ytdlp_search_entries_uses_quick_title_for_youtube_url_only_rows():
    site = {"id": "yvsearch", "label": "Yahoo Video", "search_key": "yvsearch"}
    entries = [{"_type": "url", "url": "https://www.youtube.com/watch?v=gWB-J0EEFac"}]

    with patch("core.discovery._resolve_quick_url_title_cached", return_value="Real Video Title"):
        out = discovery._normalize_ytdlp_search_entries(entries, site=site, limit=10)

    assert len(out) == 1
    assert out[0]["title"] == "Real Video Title"
    assert out[0]["site"] == "YouTube"
    assert out[0]["_title_is_fallback"] is False


def test_prefetch_quick_titles_for_entries_collects_supported_url_only_rows():
    entries = [
        {"title": "Has title already", "url": "https://www.youtube.com/watch?v=aaa"},
        {"_type": "url", "url": "https://www.youtube.com/watch?v=bbb"},
        {"_type": "url", "url": "https://rokfin.com/post/123"},
        {"_type": "url", "url": "https://example.com/item/1"},
    ]

    def _fake_qt(url):
        return f"T:{url.rsplit('/', 1)[-1]}"

    with patch("core.discovery._resolve_quick_url_title_cached", side_effect=_fake_qt):
        out = discovery._prefetch_quick_titles_for_entries(entries, limit=10)

    assert "https://www.youtube.com/watch?v=bbb" in out
    assert "https://rokfin.com/post/123" in out
    assert "https://example.com/item/1" not in out


def test_run_ytdlp_query_search_accepts_zero_returncode():
    class _FakeProc:
        returncode = 0
        stdout = b'{"entries":[{"title":"X","url":"https://example.com/x"}]}'
        stderr = b""

    with patch("core.discovery.subprocess.run", return_value=_FakeProc()), patch(
        "core.discovery.platform.system", return_value="Windows"
    ), patch("core.dependency_check._get_startup_info", return_value=None):
        out = discovery._run_ytdlp_query_search("ytsearch", "north korea", limit=3, timeout=10)

    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["url"] == "https://example.com/x"


def test_resolve_ytdlp_url_title_prefers_ytdlp_title():
    class _FakeYDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            assert download is False
            return {"title": "Resolved Name", "webpage_url": url}

    fake_mod = types.SimpleNamespace(YoutubeDL=_FakeYDL)
    with patch.dict(sys.modules, {"yt_dlp": fake_mod}), patch(
        "core.dependency_check._get_startup_info", return_value=None
    ), patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]):
        title = discovery.resolve_ytdlp_url_title("https://example.com/watch/1", timeout=8)

    assert title == "Resolved Name"


def test_resolve_quick_url_title_uses_youtube_oembed():
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"title": "Quick YT Title"}

    with patch("core.discovery.utils.safe_requests_get", return_value=_Resp()) as mock_get:
        title = discovery.resolve_quick_url_title("https://www.youtube.com/watch?v=C4W_zvyoJu8", timeout=4)

    assert title == "Quick YT Title"
    assert mock_get.called


def test_resolve_quick_url_title_uses_rokfin_public_api():
    with patch("core.discovery._youtube_oembed_title", return_value=""), patch(
        "core.discovery._rokfin_public_api_enrichment",
        return_value={"title": "Quick Rokfin Title"},
    ) as mock_rk:
        title = discovery.resolve_quick_url_title("https://rokfin.com/post/56518", timeout=4)

    assert title == "Quick Rokfin Title"
    assert mock_rk.called


def test_rokfin_public_api_enrichment_falls_back_post_id_to_stream_endpoint():
    class _Resp:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

        def json(self):
            return self._data

    def _fake_get(url, **kwargs):
        if url.endswith("/post/46132"):
            return _Resp(404, {"error": "Not Found"})
        if url.endswith("/stream/46132"):
            return _Resp(
                200,
                {
                    "title": "Government Dogman and Fireball Friday - Open lines show",
                    "creator": {"username": "ShepardAmbellas"},
                },
            )
        raise AssertionError(f"Unexpected URL {url}")

    with patch("core.discovery.utils.safe_requests_get", side_effect=_fake_get):
        out = discovery._rokfin_public_api_enrichment("https://rokfin.com/post/46132", timeout=8)

    assert out["title"] == "Government Dogman and Fireball Friday - Open lines show"
    assert out["source_subscribe_url"] == "https://rokfin.com/ShepardAmbellas"


def test_rokfin_public_api_enrichment_supports_stack_urls():
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "content": [
                    {
                        "text": "LB vs LSN Dual: Interview",
                        "createdBy": {"username": "MissouriWrestling"},
                        "content": {"contentTitle": "Lee's Summit North's Charlie Dykes (113)"},
                    }
                ]
            }

    with patch("core.discovery.utils.safe_requests_get", return_value=_Resp()):
        out = discovery._rokfin_public_api_enrichment("https://rokfin.com/stack/1176", timeout=8)

    assert out["title"] == "LB vs LSN Dual: Interview"
    assert out["source_subscribe_url"] == "https://rokfin.com/MissouriWrestling"


def test_resolve_ytdlp_url_title_falls_back_to_html_metadata():
    class _BoomYDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _url, download=False):
            raise RuntimeError("yt-dlp failed")

    fake_mod = types.SimpleNamespace(YoutubeDL=_BoomYDL)
    with patch.dict(sys.modules, {"yt_dlp": fake_mod}), patch(
        "core.dependency_check._get_startup_info", return_value=None
    ), patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
        "core.discovery._fetch_url_title_from_html", return_value="Page Title"
    ):
        title = discovery.resolve_ytdlp_url_title("https://example.com/watch/2", timeout=8)

    assert title == "Page Title"


def test_resolve_ytdlp_url_enrichment_uses_rokfin_public_api_fallback():
    class _BoomYDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, _url, download=False):
            raise RuntimeError("yt-dlp failed")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "title": "Rokfin Real Title",
                "createdBy": {"username": "Truthwire"},
            }

    fake_mod = types.SimpleNamespace(YoutubeDL=_BoomYDL)
    with patch.dict(sys.modules, {"yt_dlp": fake_mod}), patch(
        "core.dependency_check._get_startup_info", return_value=None
    ), patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
        "core.discovery.utils.safe_requests_get", return_value=_Resp()
    ) as mock_get, patch("core.discovery._fetch_url_title_from_html", return_value=""):
        out = discovery.resolve_ytdlp_url_enrichment("https://rokfin.com/post/56518", timeout=8)

    assert out["title"] == "Rokfin Real Title"
    assert out["source_subscribe_url"] == "https://rokfin.com/Truthwire"
    assert mock_get.called


def test_probe_rokfin_public_playback_reports_auth_required():
    class _Resp:
        def __init__(self, status_code=200, data=None, text="", headers=None, url=""):
            self.status_code = status_code
            self._data = data
            self.text = text
            self.headers = headers or {}
            self.url = url or "https://example.test/"

        def json(self):
            return self._data

    def _fake_get(url, **kwargs):
        if "/public/post/109843" in url:
            return _Resp(
                200,
                data={
                    "createdBy": {"username": "WorldWrestling"},
                    "content": {
                        "contentId": 70211,
                        "contentTitle": "World Wrestling Resource",
                        "contentUrl": "https://stream.v.rokfin.com/badid.m3u8",
                    },
                },
                url=url,
            )
        if "/public/content/70211" in url:
            return _Resp(200, data={"is_authorized": False, "content": None, "offers": [{"id": "offer"}]}, url=url)
        raise AssertionError(f"Unexpected URL {url}")

    with patch("core.discovery.utils.safe_requests_get", side_effect=_fake_get):
        out = discovery.probe_rokfin_public_playback("https://rokfin.com/post/109843", timeout=8)

    assert out["ok"] is False
    assert out["reason"] == "auth_required"
    assert "not authorized" in out["detail"].lower()


def test_probe_rokfin_public_playback_reports_invalid_playback_id():
    class _Resp:
        def __init__(self, status_code=200, data=None, text="", headers=None, url=""):
            self.status_code = status_code
            self._data = data
            self.text = text
            self.headers = headers or {}
            self.url = url or "https://example.test/"

        def json(self):
            return self._data

    def _fake_get(url, **kwargs):
        if "/public/post/1" in url:
            return _Resp(
                200,
                data={
                    "createdBy": {"username": "Creator"},
                    "content": {
                        "contentId": 11,
                        "contentTitle": "Title",
                        "contentUrl": "https://stream.v.rokfin.com/badid.m3u8",
                    },
                },
                url=url,
            )
        if "/public/content/11" in url:
            return _Resp(200, data={"is_authorized": True, "content": {"id": 11}, "offers": []}, url=url)
        if "stream.v.rokfin.com/badid.m3u8" in url:
            return _Resp(
                404,
                data={"error": {"messages": ["Invalid Playback ID"]}},
                text='{"error":{"messages":["Invalid Playback ID"],"type":"not_found"}}',
                headers={"content-type": "application/json"},
                url=url,
            )
        raise AssertionError(f"Unexpected URL {url}")

    with patch("core.discovery.utils.safe_requests_get", side_effect=_fake_get):
        out = discovery.probe_rokfin_public_playback("https://rokfin.com/post/1", timeout=8)

    assert out["ok"] is False
    assert out["reason"] == "invalid_playback_id"
