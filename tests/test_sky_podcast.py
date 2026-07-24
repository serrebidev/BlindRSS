from types import SimpleNamespace

from core import article_extractor, discovery, sky


ARTICLE_URL = "https://news.sky.com/story/is-the-no-wars-president-about-to-start-another-one-13566499"
TITLE = "Is the 'no wars' president about to start another one?"
PODFOLLOW_URL = "https://podfollow.com/trump100/view"
FEED_URL = "https://feeds.captivate.fm/trump100/"
MP3_URL = "https://episodes.captivate.fm/episode/sky-test.mp3?tracking=1"


def _response(*, text="", content=None, status=200):
    if content is None:
        content = text.encode("utf-8")
    return SimpleNamespace(
        status_code=status,
        text=text,
        content=content,
        encoding="utf-8",
        apparent_encoding="utf-8",
    )


def _podfollow_html():
    return f'''<html><script type="application/ld+json">{{
      "@type": "PodcastSeries", "webFeed": "pcast://feeds.captivate.fm/trump100/"
    }}</script></html>'''


def _feed_xml():
    return f'''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Trump 100</title><item>
      <title>{TITLE}</title>
      <enclosure url="{MP3_URL.replace('&', '&amp;')}" type="audio/mpeg" length="123" />
    </item></channel></rss>'''.encode("utf-8")


def test_sky_podcast_audio_follows_podfollow_feed_and_matches_title(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url == PODFOLLOW_URL:
            return _response(text=_podfollow_html())
        if url == FEED_URL:
            return _response(content=_feed_xml())
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr(sky.utils, "safe_requests_get", fake_get)

    assert sky.extract_podcast_audio(
        ARTICLE_URL,
        title=TITLE,
        html_hint=f'<a href="{PODFOLLOW_URL}">Follow Trump100</a>',
    ) == (MP3_URL, "audio/mpeg")
    assert calls == [PODFOLLOW_URL, FEED_URL]


def test_detect_media_uses_sky_resolver_before_ytdlp(monkeypatch):
    monkeypatch.setattr(
        sky,
        "extract_podcast_audio",
        lambda url, timeout: (MP3_URL, "audio/mpeg"),
    )

    assert discovery.detect_media(ARTICLE_URL) == (MP3_URL, "audio/mpeg")


def test_sky_gate_fallback_extracts_podcast_article_text(monkeypatch):
    gate = "Powered and protected by Akamai Privacy"
    recovered = f'''<html><head>
      <title>{TITLE} | World News | Sky News</title>
      <script type="application/ld+json">{{
        "@type": "NewsArticle",
        "headline": "{TITLE}",
        "articleBody": "Is Donald Trump about to bomb Mali? Yes - you read that right. Not content with a war in Iran, he's also mulling strikes on the West African country. <p>Why? What for? We'll explain.</p><p>Plus, the programme examines the latest agreement between the United States and Saudi Arabia.</p>"
      }}</script>
    </head><body></body></html>'''

    def fake_get(url, **kwargs):
        if "translate.goog" in url:
            return _response(text=recovered)
        return _response(text=gate, status=403)

    monkeypatch.setattr(article_extractor.utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(article_extractor, "_download_via_impersonation", lambda *a: None)
    monkeypatch.setattr(article_extractor, "_download_via_smry", lambda *a: None)
    monkeypatch.setattr(article_extractor, "_download_via_wayback", lambda *a: None)
    monkeypatch.setattr(article_extractor, "_download_via_browser", lambda *a: None)

    article = article_extractor.extract_full_article(ARTICLE_URL, max_pages=1)
    assert "Is Donald Trump about to bomb Mali?" in article.text
    assert "Why? What for? We'll explain." in article.text
    assert "Powered and protected by" not in article.text
