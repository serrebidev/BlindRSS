# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Miniflux TLS trust and user-visible connection diagnostics."""

import ssl

import requests

import gui.mainframe as mainframe
from providers.miniflux import MinifluxProvider, _SystemTrustHTTPAdapter


def _provider() -> MinifluxProvider:
    return MinifluxProvider(
        {
            "feed_retry_attempts": 0,
            "providers": {
                "miniflux": {
                    "url": "https://reader.internal",
                    "api_key": "secret",
                }
            },
        }
    )


def test_miniflux_https_adapter_starts_with_system_trust_context():
    provider = _provider()

    adapter = provider._session.adapters["https://"]
    assert isinstance(adapter, _SystemTrustHTTPAdapter)
    context = adapter.poolmanager.connection_pool_kw["ssl_context"]
    assert context is adapter._system_ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_miniflux_preserves_actionable_tls_error(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        provider._session,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.exceptions.SSLError("unable to get local issuer certificate")
        ),
    )

    assert provider.get_feeds() == []
    message = provider.get_connection_error()
    assert "TLS certificate verification failed" in message
    assert "operating system certificate store" in message
    assert "unable to get local issuer certificate" in message


def test_failed_miniflux_tree_load_schedules_accessible_error_dialog(monkeypatch):
    calls = []

    class _Provider:
        def get_feeds(self):
            return []

        def get_connection_error(self):
            return "TLS certificate verification failed for https://reader.internal."

    class _Host:
        provider = _Provider()
        _refresh_feeds_worker = mainframe.MainFrame._refresh_feeds_worker

    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda *args: calls.append(args))

    _Host()._refresh_feeds_worker()

    assert len(calls) == 1
    callback, message, title, style = calls[0]
    assert callback is mainframe.wx.MessageBox
    assert "TLS certificate verification failed" in message
    assert title == "Error"
    assert style == mainframe.wx.ICON_ERROR
