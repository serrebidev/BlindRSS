# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shared test-suite guards.

The full-text and feed paths both escalate to `core.browser_feed`, which starts a
real (serialized, several-second) Chromium session. A unit test that mocks HTTP
would otherwise sail past its mock into that launch and hit the live network, so
the escalation is disabled for the whole suite. Tests that exercise the browser
fallback deliberately can monkeypatch `core.browser_feed` themselves.

The managed cookie jar is redirected for the same reason: request behavior now
depends on whether the jar holds a session for the host under test (a pinned
User-Agent forces a matching TLS fingerprint), so a suite reading the developer's
real jar would pass or fail based on which sites they happen to have visited.
`test_impersonation_falls_through_to_safari_fingerprint` really did start failing
on a machine whose owner had browsed neowin.net.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _no_real_browser_launch(monkeypatch):
    try:
        from core import browser_feed
    except Exception:
        return
    monkeypatch.setattr(
        browser_feed,
        "_fetch_browser_document",
        lambda *args, **kwargs: None,
        raising=False,
    )


@pytest.fixture(autouse=True)
def _no_automatic_podcast_archive_network(monkeypatch):
    """Unit tests never enqueue live Archive.org background work."""
    try:
        from core import podcast_archive
    except Exception:
        return
    monkeypatch.setattr(podcast_archive, "enqueue_archive_job", lambda _job: None)


@pytest.fixture(autouse=True)
def _isolated_site_cookie_jar(tmp_path_factory, monkeypatch):
    try:
        from core import site_cookies
    except Exception:
        return
    # All tests can share one suite-scoped empty location because the managed
    # jar is invalidated before and after every case below.  mktemp() here used
    # to create almost two thousand directories during a full run, adding
    # avoidable filesystem/antivirus CPU overhead on Windows.
    jar_dir = tmp_path_factory.getbasetemp() / "site-cookies"
    jar_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(jar_dir))
    # Profile discovery is independent of the jar path, and the gate-recovery
    # path reads it: without this a test would copy and parse the developer's
    # real browser cookie databases, and its result would depend on which sites
    # they had visited. Stubbed at the roots rather than at
    # list_browser_profiles() so the real discovery code still runs and tests
    # that supply their own fake roots keep working.
    monkeypatch.setattr(site_cookies, "_firefox_like_roots", lambda: [])

    # Tests that write the managed jar/UA files (set_user_agent,
    # set_host_user_agent, import_jar) must not leak into the next case: a
    # persisted UA + clearance cookie changed which fingerprint later
    # full-text tests used, making them order-dependent. Clear the scratch
    # files on both sides of every test.
    def _reset():
        for name in (
            site_cookies.JAR_FILENAME,
            site_cookies.UA_FILENAME,
            site_cookies.HOST_UA_FILENAME,
        ):
            try:
                os.remove(os.path.join(str(jar_dir), name))
            except OSError:
                pass
        site_cookies._invalidate()

    _reset()
    site_cookies._last_forced_refresh.clear()
    yield
    _reset()
    site_cookies._last_forced_refresh.clear()
