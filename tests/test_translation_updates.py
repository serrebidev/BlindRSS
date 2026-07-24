"""Over-the-air translation catalog updates (no app release required).

The risk these guard against is not "did it download" but "can a bad download
break the UI": a truncated or empty catalog installed over a good one would
blank labels across the whole app for a screen-reader user, and only a
reinstall would bring them back.
"""
import os

import pytest

from core import i18n, po_compile, translation_updates as tu


PO = '''
msgid ""
msgstr "Content-Type: text/plain; charset=UTF-8\\n"

msgid "All Articles"
msgstr "Все статьи"

msgid "Favorites"
msgstr "Избранное"
'''


def _po_with(count):
    body = [PO]
    for i in range(count):
        body.append(f'\nmsgid "key {i}"\nmsgstr "value {i}"\n')
    return "".join(body)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tu, "override_root", lambda: str(tmp_path / "locale"))
    monkeypatch.setattr(tu, "_state_path", lambda: str(tmp_path / "state.json"))
    return tmp_path


class _Resp:
    def __init__(self, status=200, text="", etag="new-etag", encoding="utf-8"):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"ETag": etag} if etag else {}
        self.encoding = encoding

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _patch_get(monkeypatch, responses):
    """responses: dict lang -> _Resp, or a callable(url, headers, timeout)."""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, dict(headers or {})))
        if callable(responses):
            return responses(url, headers, timeout)
        for lang, resp in responses.items():
            if f"/{lang}/" in url:
                return resp
        return _Resp(404)

    monkeypatch.setattr("core.utils.safe_requests_get", fake_get)
    return calls


def test_downloads_and_compiles_a_catalog(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60))})

    result = tu.check_and_update(["ru"])

    assert result.ok and result.updated == ["ru"]
    mo = tu.catalog_path("ru")
    assert os.path.isfile(mo)
    # The compiled catalog is real and readable by gettext's own reader.
    import gettext

    with open(mo, "rb") as fh:
        assert gettext.GNUTranslations(fh).gettext("All Articles") == "Все статьи"


def test_unchanged_catalog_is_not_rewritten(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60), etag='"abc"')})
    tu.check_and_update(["ru"])
    first = os.path.getmtime(tu.catalog_path("ru"))

    calls = _patch_get(monkeypatch, {"ru": _Resp(status=304, text="")})
    result = tu.check_and_update(["ru"])

    assert result.ok and result.updated == []
    assert os.path.getmtime(tu.catalog_path("ru")) == first
    # The stored ETag must actually be sent, or every check re-downloads.
    assert calls[0][1].get("If-None-Match") == '"abc"'


def test_truncated_download_never_replaces_a_good_catalog(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60))})
    tu.check_and_update(["ru"])
    good = open(tu.catalog_path("ru"), "rb").read()

    # A half-received PO parses to only a couple of messages.
    _patch_get(monkeypatch, {"ru": _Resp(text='msgid "All Articles"\nmsgstr "x"\n', etag='"z"')})
    result = tu.check_and_update(["ru"], force=True)

    assert result.updated == []
    assert open(tu.catalog_path("ru"), "rb").read() == good


def test_empty_response_never_blanks_the_ui(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60))})
    tu.check_and_update(["ru"])
    good = open(tu.catalog_path("ru"), "rb").read()

    _patch_get(monkeypatch, {"ru": _Resp(text="", etag='"z"')})
    tu.check_and_update(["ru"], force=True)

    assert open(tu.catalog_path("ru"), "rb").read() == good


def test_network_error_is_reported_not_raised(data_dir, monkeypatch):
    def boom(url, headers=None, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr("core.utils.safe_requests_get", boom)

    result = tu.check_and_update(["ru"])

    assert not result.ok
    assert "no route" in result.error
    assert result.updated == []


def test_english_is_never_fetched(data_dir, monkeypatch):
    calls = _patch_get(monkeypatch, {})
    result = tu.check_and_update(["en"])
    assert calls == []
    assert result.checked == []


def test_missing_upstream_catalog_is_not_an_error(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"zz": _Resp(404)})
    result = tu.check_and_update(["zz"])
    assert result.ok
    assert result.updated == []


def test_refetches_when_state_has_etag_but_file_is_gone(data_dir, monkeypatch):
    _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60), etag='"abc"')})
    tu.check_and_update(["ru"])
    os.unlink(tu.catalog_path("ru"))

    calls = _patch_get(monkeypatch, {"ru": _Resp(text=_po_with(60), etag='"abc"')})
    result = tu.check_and_update(["ru"])

    # No If-None-Match, because trusting it would leave the user with no catalog.
    assert calls[0][1].get("If-None-Match") is None
    assert result.updated == ["ru"]
    assert os.path.isfile(tu.catalog_path("ru"))


def test_mislabelled_encoding_still_decodes_as_utf8(data_dir, monkeypatch):
    # requests guesses latin-1 for text/plain with no charset; PO files are UTF-8.
    text = _po_with(60)
    resp = _Resp(text=text, encoding="ISO-8859-1")
    resp.text = text.encode("utf-8").decode("latin-1")
    _patch_get(monkeypatch, {"ru": resp})

    tu.check_and_update(["ru"])

    import gettext

    with open(tu.catalog_path("ru"), "rb") as fh:
        assert gettext.GNUTranslations(fh).gettext("All Articles") == "Все статьи"


def test_is_due_respects_frequency(data_dir, monkeypatch):
    assert tu.is_due("daily") is True  # never checked
    tu.save_state({"last_check": 1_000_000})
    assert tu.is_due("daily", now=1_000_000 + 60) is False
    assert tu.is_due("daily", now=1_000_000 + 25 * 3600) is True
    assert tu.is_due("weekly", now=1_000_000 + 25 * 3600) is False


def test_downloaded_catalog_wins_over_bundled(tmp_path, monkeypatch):
    """The whole point: an override must take precedence over the bundle."""
    bundled = tmp_path / "bundled"
    override = tmp_path / "override"
    for root, text in ((bundled, "bundled text"), (override, "downloaded text")):
        path = root / "xx" / "LC_MESSAGES" / "blindrss.mo"
        path.parent.mkdir(parents=True)
        po_compile.write_mo({"All Articles": text}, path)

    monkeypatch.setattr(i18n, "locale_dir", lambda: str(bundled))
    monkeypatch.setattr(i18n, "override_locale_dir", lambda: str(override))
    try:
        i18n.setup("xx")
        assert i18n._("All Articles") == "downloaded text"
    finally:
        i18n.setup("en")


def test_falls_back_to_bundled_when_language_not_downloaded(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    override = tmp_path / "override"
    path = bundled / "xx" / "LC_MESSAGES" / "blindrss.mo"
    path.parent.mkdir(parents=True)
    po_compile.write_mo({"All Articles": "bundled text"}, path)
    (override / "yy" / "LC_MESSAGES").mkdir(parents=True)

    monkeypatch.setattr(i18n, "locale_dir", lambda: str(bundled))
    monkeypatch.setattr(i18n, "override_locale_dir", lambda: str(override))
    try:
        i18n.setup("xx")
        assert i18n._("All Articles") == "bundled text"
    finally:
        i18n.setup("en")
