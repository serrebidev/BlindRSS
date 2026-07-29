# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""CAPTCHA-solving-service client tests (offline; HTTP mocked)."""

import threading

import pytest

from core import captcha_solver


@pytest.fixture(autouse=True)
def _clean_settings():
    captcha_solver.configure({})
    yield
    captcha_solver.configure({})


@pytest.fixture
def _no_delays(monkeypatch):
    monkeypatch.setattr(captcha_solver, "_FIRST_POLL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(captcha_solver, "_POLL_INTERVAL_SECONDS", 0.0)


def test_configure_roundtrip_and_gating():
    assert captcha_solver.solver_available() is False

    captcha_solver.configure({"enabled": True, "provider": "SolveCaptcha", "api_key": " k "})
    settings = captcha_solver.current_settings()
    assert settings == {"enabled": True, "provider": "solvecaptcha", "api_key": "k"}
    assert captcha_solver.solver_available() is True

    # An unknown provider falls back to the default rather than breaking.
    captcha_solver.configure({"enabled": True, "provider": "nope", "api_key": "k"})
    assert captcha_solver.current_settings()["provider"] == "2captcha"

    # Enabled without a key is not usable.
    captcha_solver.configure({"enabled": True, "provider": "2captcha", "api_key": ""})
    assert captcha_solver.solver_available() is False


def test_configure_from_config():
    values = {
        "captcha_solver_enabled": True,
        "captcha_solver_provider": "solvecaptcha",
        "captcha_solver_api_key": "abc",
    }
    captcha_solver.configure_from_config(lambda key, default=None: values.get(key, default))
    assert captcha_solver.current_settings()["api_key"] == "abc"
    assert captcha_solver.solver_available() is True


class _FakeHTTP:
    def __init__(self, post_results, get_results):
        self.post_results = list(post_results)
        self.get_results = list(get_results)
        self.posts = []
        self.gets = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, data, timeout))
        return _Resp(self.post_results.pop(0))

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params, timeout))
        return _Resp(self.get_results.pop(0))


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_solve_turnstile_success(monkeypatch, _no_delays):
    http = _FakeHTTP(
        post_results=[{"status": 1, "request": "task-1"}],
        get_results=[
            {"status": 0, "request": "CAPCHA_NOT_READY"},
            {"status": 1, "request": "solved-token"},
        ],
    )
    monkeypatch.setattr(captcha_solver, "requests", http)

    token = captcha_solver.solve_turnstile(
        api_key="key",
        provider="solvecaptcha",
        sitekey="0xSITEKEY",
        pageurl="https://gated.example/feed",
        data="cdata",
        pagedata="pdata",
        action="managed",
        user_agent="UA/1.0",
    )

    assert token == "solved-token"
    url, payload, timeout = http.posts[0]
    assert url == "https://api.solvecaptcha.com/in.php"
    assert payload["method"] == "turnstile"
    assert payload["sitekey"] == "0xSITEKEY"
    assert payload["data"] == "cdata"
    assert payload["pagedata"] == "pdata"
    assert payload["action"] == "managed"
    assert payload["userAgent"] == "UA/1.0"
    assert timeout == captcha_solver._HTTP_TIMEOUT_SECONDS
    poll_url, poll_params, _ = http.gets[0]
    assert poll_url == "https://api.solvecaptcha.com/res.php"
    assert poll_params["id"] == "task-1"


def test_solve_turnstile_uses_2captcha_endpoints_by_default(monkeypatch, _no_delays):
    http = _FakeHTTP(
        post_results=[{"status": 1, "request": "task-1"}],
        get_results=[{"status": 1, "request": "tok"}],
    )
    monkeypatch.setattr(captcha_solver, "requests", http)

    token = captcha_solver.solve_turnstile(
        api_key="key", provider="2captcha", sitekey="sk", pageurl="https://x.example/"
    )
    assert token == "tok"
    assert http.posts[0][0] == "https://2captcha.com/in.php"


def test_solve_turnstile_submit_rejection_returns_none(monkeypatch, _no_delays):
    http = _FakeHTTP(post_results=[{"status": 0, "request": "ERROR_KEY_DOES_NOT_EXIST"}], get_results=[])
    monkeypatch.setattr(captcha_solver, "requests", http)
    assert (
        captcha_solver.solve_turnstile(api_key="bad", provider="2captcha", sitekey="sk", pageurl="https://x.example/")
        is None
    )


def test_solve_turnstile_task_error_returns_none(monkeypatch, _no_delays):
    http = _FakeHTTP(
        post_results=[{"status": 1, "request": "task-1"}],
        get_results=[{"status": 0, "request": "ERROR_CAPTCHA_UNSOLVABLE"}],
    )
    monkeypatch.setattr(captcha_solver, "requests", http)
    assert (
        captcha_solver.solve_turnstile(api_key="key", provider="2captcha", sitekey="sk", pageurl="https://x.example/")
        is None
    )


def test_solve_turnstile_requires_sitekey_and_url():
    assert captcha_solver.solve_turnstile(api_key="k", provider="2captcha", sitekey="", pageurl="https://x.example/") is None
    assert captcha_solver.solve_turnstile(api_key="k", provider="2captcha", sitekey="sk", pageurl="") is None
    assert captcha_solver.solve_turnstile(api_key="k", provider="unknown", sitekey="sk", pageurl="https://x.example/") is None


def test_solve_turnstile_honors_cancellation(monkeypatch):
    http = _FakeHTTP(post_results=[{"status": 1, "request": "task-1"}], get_results=[])
    monkeypatch.setattr(captcha_solver, "requests", http)
    cancel = threading.Event()
    cancel.set()
    assert (
        captcha_solver.solve_turnstile(
            api_key="k", provider="2captcha", sitekey="sk", pageurl="https://x.example/", cancel_event=cancel
        )
        is None
    )
