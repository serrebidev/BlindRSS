import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.translation as tr


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = int(status_code)
        self._payload = payload if payload is not None else {}
        self.text = text
        self.ok = 200 <= int(status_code) < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.ok:
            return None
        import requests

        err = requests.HTTPError(f"{self.status_code} error")
        err.response = self
        raise err


def test_iter_text_chunks_splits_large_text():
    text = ("Para1 line\n\n" + ("x" * 2100) + "\n\n" + ("y" * 2100))
    chunks = list(tr._iter_text_chunks(text, max_chars=2500))

    assert len(chunks) >= 2
    assert "".join(chunks) == text
    assert all(len(c) <= 2500 for c in chunks)


def test_translate_text_grok_retries_on_missing_model(monkeypatch):
    calls = []

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append(
            {
                "url": url,
                "auth": (headers or {}).get("Authorization"),
                "model": (json or {}).get("model"),
                "timeout": timeout,
            }
        )
        if len(calls) == 1:
            return _Resp(
                400,
                payload={"error": "model not found"},
                text='{"error":"model not found"}',
            )
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Bonjour"}}
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_grok(
        "Hello",
        api_key="secret-key",
        target_language="fr",
        model_candidates=["missing-model", "working-model"],
        timeout_s=12,
        chunk_chars=1000,
    )

    assert out == "Bonjour"
    assert len(calls) == 2
    assert calls[0]["model"] == "missing-model"
    assert calls[1]["model"] == "working-model"
    assert calls[0]["auth"] == "Bearer secret-key"
    assert int(calls[1]["timeout"]) == 12


def test_translate_text_grok_retries_on_model_access_denied(monkeypatch):
    calls = []

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append((json or {}).get("model"))
        if len(calls) == 1:
            return _Resp(
                403,
                payload={"error": {"message": "You do not have access to model grok-4-fast-non-reasoning"}},
                text='{"error":{"message":"You do not have access to model grok-4-fast-non-reasoning"}}',
            )
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Hola"}}
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_grok(
        "Hello",
        api_key="secret-key",
        target_language="es",
        model_candidates=["grok-4-fast-non-reasoning", "grok-3-mini"],
        timeout_s=12,
        chunk_chars=1000,
    )

    assert out == "Hola"
    assert calls == ["grok-4-fast-non-reasoning", "grok-3-mini"]


def test_translate_text_dispatches_to_grok(monkeypatch):
    seen = {}

    def _fake_translate_text_grok(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_grok", _fake_translate_text_grok)
    assert (
        tr.translate_text(
            "Hello",
            provider="grok",
            api_key="k",
            target_language="de",
            grok_model="grok-3-mini",
        )
        == "Translated"
    )
    assert seen["kwargs"]["model"] == "grok-3-mini"


def test_translate_text_grok_uses_explicit_model_only(monkeypatch):
    calls = []

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append((json or {}).get("model"))
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Hallo"}}
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_grok(
        "Hello",
        api_key="secret-key",
        target_language="de",
        model="my-custom-grok-model",
        model_candidates=["ignored-a", "ignored-b"],
        timeout_s=12,
        chunk_chars=1000,
    )

    assert out == "Hallo"
    assert calls == ["my-custom-grok-model"]


def test_default_grok_model_candidates_include_fast_non_reasoning_variants():
    candidates = tuple(getattr(tr, "_DEFAULT_MODEL_CANDIDATES", ()))
    assert "grok-4-fast-non-reasoning" in candidates
    assert "grok-4-1-fast-non-reasoning" in candidates


def test_translate_text_grok_routes_groq_keys_to_groq_endpoint(monkeypatch):
    seen = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = str(url)
        seen["auth"] = (headers or {}).get("Authorization")
        seen["model"] = (json or {}).get("model")
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Hola"}}
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_grok(
        "Hello",
        api_key="gsk_test_secret",
        target_language="es",
        timeout_s=12,
        chunk_chars=1000,
    )

    assert out == "Hola"
    assert str(seen.get("url") or "").startswith("https://api.groq.com/openai/v1/chat/completions")
    assert seen.get("auth") == "Bearer gsk_test_secret"
