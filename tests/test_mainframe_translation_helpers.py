import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _DummyMain:
    _translation_runtime_config = mainframe.MainFrame._translation_runtime_config
    _translation_fulltext_cache_suffix = mainframe.MainFrame._translation_fulltext_cache_suffix
    _fulltext_cache_key_for_article = mainframe.MainFrame._fulltext_cache_key_for_article
    _should_prefer_feed_fulltext = mainframe.MainFrame._should_prefer_feed_fulltext
    _translate_rendered_text_if_enabled = mainframe.MainFrame._translate_rendered_text_if_enabled

    def __init__(self, config_values=None):
        self.config_manager = _Cfg(config_values or {})


def test_fulltext_cache_key_includes_translation_suffix_when_enabled():
    host = _DummyMain(
        {
            "translation_enabled": True,
            "translation_provider": "grok",
            "translation_target_language": "ru",
            "translation_grok_api_key": "secret",
        }
    )
    article = SimpleNamespace(url="https://example.com/a", id="a1")
    cache_key, url, aid = host._fulltext_cache_key_for_article(article, 0)

    assert url == "https://example.com/a"
    assert aid == "a1"
    assert cache_key.endswith("::tr[grok:ru]")


def test_fulltext_cache_key_includes_grok_model_when_configured():
    host = _DummyMain(
        {
            "translation_enabled": True,
            "translation_provider": "grok",
            "translation_target_language": "ru",
            "translation_grok_model": "grok-3",
            "translation_grok_api_key": "secret",
        }
    )
    article = SimpleNamespace(url="https://example.com/a", id="a1")
    cache_key, _url, _aid = host._fulltext_cache_key_for_article(article, 0)

    assert cache_key.endswith("::tr[grok:ru:grok-3]")


def test_translate_rendered_text_if_enabled_falls_back_on_error(monkeypatch):
    host = _DummyMain(
        {
            "translation_enabled": True,
            "translation_provider": "grok",
            "translation_target_language": "fr",
            "translation_grok_api_key": "secret",
        }
    )
    monkeypatch.setattr(
        mainframe.translation_mod,
        "translate_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    text = "Original content"
    assert host._translate_rendered_text_if_enabled(text) == text


def test_translate_rendered_text_passes_grok_model(monkeypatch):
    host = _DummyMain(
        {
            "translation_enabled": True,
            "translation_provider": "grok",
            "translation_target_language": "fr",
            "translation_grok_model": "grok-3",
            "translation_grok_api_key": "secret",
        }
    )
    seen = {}

    def _fake_translate_text(text, **kwargs):
        seen["text"] = text
        seen["kwargs"] = dict(kwargs)
        return "Translated content"

    monkeypatch.setattr(mainframe.translation_mod, "translate_text", _fake_translate_text)

    out = host._translate_rendered_text_if_enabled("Original content")

    assert out == "Translated content"
    assert seen["text"] == "Original content"
    assert seen["kwargs"]["grok_model"] == "grok-3"


def test_should_prefer_feed_fulltext_for_ning_forum_comment_link_is_false():
    host = _DummyMain()
    html = """
    <div><a href="https://creators.ning.com/members/ScottBishop">Scott Bishop</a>
    <a href="https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942">replied</a>
    to <a href="https://creators.ning.com/members/Alex">Alex</a>'s discussion</div>
    <div><div>Reply excerpt text.</div></div>
    """
    assert host._should_prefer_feed_fulltext(
        "https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942",
        html,
    ) is False


def test_should_prefer_feed_fulltext_for_ning_profile_link_is_true():
    host = _DummyMain()
    html = "<div>Kathleen (SunKat) updated their <a href='https://creators.ning.com/members/Kathleen_aka_SunKat'>profile</a></div>"
    assert host._should_prefer_feed_fulltext(
        "https://creators.ning.com/members/Kathleen_aka_SunKat",
        html,
    ) is True


def test_should_prefer_feed_fulltext_ignores_placeholder_content():
    host = _DummyMain()
    html = "unable to retrieve full-text content" + ("x" * 4000)
    assert host._should_prefer_feed_fulltext("https://www.techrepublic.com/article/test/", html) is False
