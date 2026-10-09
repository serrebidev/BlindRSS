import hashlib

from core import sponsorblock


def _cfg(values):
    return lambda key, default=None: values.get(key, default)


def test_parse_keeps_only_this_video_and_skip_segments():
    data = [
        {"videoID": "other", "segments": [{"category": "sponsor", "segment": [1, 9], "UUID": "x"}]},
        {
            "videoID": "abc123def45",
            "segments": [
                {"category": "outro", "actionType": "skip", "segment": [90, 100], "UUID": "b"},
                {"category": "sponsor", "actionType": "skip", "segment": [10, 40.5], "UUID": "a"},
                {"category": "poi_highlight", "actionType": "poi", "segment": [5, 5], "UUID": "c"},
                {"category": "sponsor", "actionType": "skip", "segment": [50, 50.2], "UUID": "tiny"},
            ],
        },
    ]
    segs = sponsorblock.parse_segments(data, "abc123def45")
    assert [s["uuid"] for s in segs] == ["a", "b"]
    assert segs[0] == {"start": 10.0, "end": 40.5, "category": "sponsor", "uuid": "a"}


def test_segment_at_skips_once_and_ignores_tail():
    segs = [{"start": 10.0, "end": 40.0, "category": "sponsor", "uuid": "a"}]
    assert sponsorblock.segment_at(segs, 9.9) is None
    assert sponsorblock.segment_at(segs, 10.0)["uuid"] == "a"
    assert sponsorblock.segment_at(segs, 39.8) is None  # last half second
    assert sponsorblock.segment_at(segs, 20.0, done={"a"}) is None


def test_skip_categories_respects_switch_and_order():
    assert sponsorblock.skip_categories(_cfg({"sponsorblock_enabled": False})) == []
    cfg = _cfg({"sponsorblock_enabled": True, "sponsorblock_categories": ["intro", "sponsor", "bogus"]})
    assert sponsorblock.skip_categories(cfg) == ["sponsor", "intro"]


def test_fetch_sends_only_hash_prefix(monkeypatch):
    seen = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [{"videoID": "dQw4w9WgXcQ", "segments": [{"category": "sponsor", "segment": [1, 5], "UUID": "u"}]}]

    def fake_get(url, **kwargs):
        seen["url"] = url
        return Resp()

    monkeypatch.setattr(sponsorblock.utils, "safe_requests_get", fake_get)
    segs = sponsorblock.fetch_segments("dQw4w9WgXcQ", ["sponsor"])
    prefix = hashlib.sha256(b"dQw4w9WgXcQ").hexdigest()[:4]
    assert seen["url"].endswith("/" + prefix)
    assert "dQw4w9WgXcQ" not in seen["url"]
    assert segs[0]["uuid"] == "u"


def test_fetch_failure_means_no_segments(monkeypatch):
    def boom(url, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(sponsorblock.utils, "safe_requests_get", boom)
    assert sponsorblock.fetch_segments("dQw4w9WgXcQ", ["sponsor"]) == []


def test_non_youtube_url_makes_no_request(monkeypatch):
    monkeypatch.setattr(sponsorblock.utils, "safe_requests_get", lambda *a, **k: 1 / 0)
    cfg = _cfg({"sponsorblock_enabled": True})
    assert sponsorblock.segments_for_url("https://example.com/episode.mp3", cfg) == []
