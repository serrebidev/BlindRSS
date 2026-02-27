import os
import sys

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


def test_translate_text_openai_retries_on_missing_model(monkeypatch):
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
                payload={"error": {"message": "model not found"}},
                text='{"error":{"message":"model not found"}}',
            )
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Bonjour"}},
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_openai(
        "Hello",
        api_key="openai-secret",
        target_language="fr",
        model_candidates=["bad-openai-model", "gpt-4.1-mini"],
        timeout_s=9,
        chunk_chars=1000,
    )
    assert out == "Bonjour"
    assert calls[0]["model"] == "bad-openai-model"
    assert calls[1]["model"] == "gpt-4.1-mini"
    assert calls[0]["auth"] == "Bearer openai-secret"


def test_translate_text_gemini_retries_on_missing_model(monkeypatch):
    calls = []

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append(
            {
                "url": url,
                "api_key": (headers or {}).get("x-goog-api-key"),
                "parts": ((((json or {}).get("contents") or [{}])[0].get("parts") or [{}])[0].get("text") or ""),
                "timeout": timeout,
            }
        )
        if len(calls) == 1:
            return _Resp(
                404,
                payload={"error": {"message": "model not found"}},
                text='{"error":{"message":"model not found"}}',
            )
        return _Resp(
            200,
            payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Hola"},
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_gemini(
        "Hello",
        api_key="gemini-secret",
        target_language="es",
        model_candidates=["missing-gemini-model", "gemini-2.0-flash"],
        timeout_s=7,
        chunk_chars=1000,
    )

    assert out == "Hola"
    assert "missing-gemini-model" in calls[0]["url"]
    assert "gemini-2.0-flash" in calls[1]["url"]
    assert calls[0]["api_key"] == "gemini-secret"
    assert "Target language: es" in calls[1]["parts"]


def test_translate_text_dispatches_to_openai(monkeypatch):
    seen = {}

    def _fake_translate_text_openai(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_openai", _fake_translate_text_openai)
    out = tr.translate_text(
        "Hello",
        provider="openai",
        api_key="k",
        target_language="de",
        openai_model="gpt-4o-mini",
    )
    assert out == "Translated"
    assert seen["kwargs"]["model"] == "gpt-4o-mini"


def test_translate_text_dispatches_to_gemini(monkeypatch):
    seen = {}

    def _fake_translate_text_gemini(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_gemini", _fake_translate_text_gemini)
    out = tr.translate_text(
        "Hello",
        provider="gemini",
        api_key="k",
        target_language="de",
        gemini_model="gemini-2.0-flash",
    )
    assert out == "Translated"
    assert seen["kwargs"]["model"] == "gemini-2.0-flash"


def test_translate_text_qwen_retries_on_missing_model(monkeypatch):
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
                404,
                payload={"error": {"message": "model not found"}},
                text='{"error":{"message":"model not found"}}',
            )
        return _Resp(
            200,
            payload={
                "choices": [
                    {"message": {"content": "Hallo"}},
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_qwen(
        "Hello",
        api_key="qwen-secret",
        target_language="de",
        model_candidates=["missing-qwen-model", "qwen-plus"],
        timeout_s=6,
        chunk_chars=1000,
    )
    assert out == "Hallo"
    assert calls[0]["model"] == "missing-qwen-model"
    assert calls[1]["model"] == "qwen-plus"
    assert calls[0]["auth"] == "Bearer qwen-secret"


def test_translate_text_dispatches_to_qwen(monkeypatch):
    seen = {}

    def _fake_translate_text_qwen(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_qwen", _fake_translate_text_qwen)
    out = tr.translate_text(
        "Hello",
        provider="qwen",
        api_key="k",
        target_language="de",
        qwen_model="qwen-plus",
    )
    assert out == "Translated"
    assert seen["kwargs"]["model"] == "qwen-plus"
