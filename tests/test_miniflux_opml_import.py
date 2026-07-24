# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from providers.miniflux import MinifluxProvider


class _Response:
    status_code = 201

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": "Feeds imported successfully"}


def _provider():
    return MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://miniflux.example", "api_key": "token"}}}
    )


def test_miniflux_imports_entire_opml_in_one_xml_request(tmp_path, monkeypatch):
    opml = tmp_path / "takeout.opml"
    opml.write_text(
        '<?xml version="1.0"?><opml version="2.0"><body>'
        '<outline text="One" xmlUrl="https://example.com/1.xml"/>'
        '<outline text="Two" xmlUrl="https://example.com/2.xml"/>'
        "</body></opml>",
        encoding="utf-8",
    )
    provider = _provider()
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response()

    monkeypatch.setattr(provider._session, "request", request)

    assert provider.import_opml(str(opml), "YouTube") is True
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    assert method == "POST"
    assert urlparse(url).path == "/v1/import"
    assert kwargs["headers"]["Content-Type"] == "application/xml; charset=utf-8"

    root = ET.fromstring(kwargs["data"])
    folder = root.find("./body/outline")
    assert folder is not None
    assert folder.attrib["text"] == "YouTube"
    assert [node.attrib["xmlUrl"] for node in folder.findall("outline")] == [
        "https://example.com/1.xml",
        "https://example.com/2.xml",
    ]
