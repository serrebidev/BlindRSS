from types import SimpleNamespace

import pytest

from core import youtube_account


def _tile(cid, title, kind="TILE_CONTENT_TYPE_CHANNEL"):
    return {
        "tileRenderer": {
            "contentId": cid,
            "contentType": kind,
            "metadata": {"tileMetadataRenderer": {"title": {"simpleText": title}}},
        }
    }


CID_A = "UC" + "a" * 22
CID_B = "UC" + "b" * 22
CID_C = "UC" + "c" * 22

RESPONSE = {
    "contents": {
        "shelfRenderer": {
            "content": {
                "horizontalListRenderer": {
                    "items": [
                        _tile(CID_B, " Zed Channel"),
                        _tile(CID_A, "alpha"),
                        _tile(CID_A, "alpha dup"),
                        _tile("dQw4w9WgXcQ", "a video", kind="TILE_CONTENT_TYPE_VIDEO"),
                    ]
                }
            }
        }
    }
}


def test_parse_channels_dedupes_sorts_and_strips():
    assert youtube_account.parse_channels(RESPONSE) == [(CID_A, "alpha"), (CID_B, "Zed Channel")]


def test_plan_skips_known_and_existing():
    subs = [(CID_A, "A"), (CID_B, "B"), (CID_C, "C")]
    plan = youtube_account.plan_sync(subs, known=[CID_A], existing_channel_ids={CID_B})
    assert [f.url for f in plan.feeds] == [f"https://www.youtube.com/feeds/videos.xml?channel_id={CID_C}"]


class _Config(dict):
    def set(self, key, value):
        self[key] = value


def test_sync_imports_new_channels_and_remembers_all(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_account, "list_subscriptions", lambda token: [(CID_A, "A"), (CID_B, "B")])
    imported = {}

    class Provider:
        def get_feeds(self):
            return [SimpleNamespace(url=f"https://www.youtube.com/feeds/videos.xml?channel_id={CID_A}")]

        def import_opml(self, path, category):
            with open(path, encoding="utf-8") as fh:
                imported["opml"] = fh.read()
            imported["category"] = category
            return True

    config = _Config(youtube_account_refresh_token="t", youtube_account_category="Videos / Subs")
    assert youtube_account.sync(config, Provider()) == 1
    assert CID_B in imported["opml"] and CID_A not in imported["opml"]
    assert imported["category"] == "Videos / Subs"
    assert config["youtube_account_known_channels"] == sorted([CID_A, CID_B])

    # A channel the user later deleted from BlindRSS is not added back.
    imported.clear()

    class EmptyProvider(Provider):
        def get_feeds(self):
            return []

    assert youtube_account.sync(config, EmptyProvider()) == 0
    assert imported == {}


def test_sync_requires_sign_in():
    with pytest.raises(youtube_account.SignInError):
        youtube_account.sync(_Config(), None)


def test_empty_subscription_list_is_an_error(monkeypatch):
    monkeypatch.setattr(youtube_account, "access_token", lambda token: "x")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"contents": {}}

    monkeypatch.setattr(youtube_account.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(youtube_account.SignInError):
        youtube_account.list_subscriptions("t")


def test_sync_due_needs_token_switch_and_interval():
    now = 10 * youtube_account.SYNC_INTERVAL_SECONDS
    assert not youtube_account.sync_due(_Config(), now)
    cfg = _Config(youtube_account_refresh_token="t", youtube_account_last_sync=now - 60)
    assert not youtube_account.sync_due(cfg, now)
    cfg["youtube_account_last_sync"] = 0
    assert youtube_account.sync_due(cfg, now)
    cfg["youtube_account_auto_add"] = False
    assert not youtube_account.sync_due(cfg, now)
