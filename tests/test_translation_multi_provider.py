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
    assert "key=gemini-secret" in calls[0]["url"]
    assert "key=gemini-secret" in calls[1]["url"]
    assert calls[0]["api_key"] == "gemini-secret"
    assert "Target language: es" in calls[1]["parts"]


def test_translate_text_gemini_surfaces_error_detail(monkeypatch):
    def _fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(
            401,
            payload={"error": {"message": "API key not valid. Please pass a valid API key."}},
            text='{"error":{"message":"API key not valid. Please pass a valid API key."}}',
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    with pytest.raises(RuntimeError) as exc:
        tr.translate_text_gemini(
            "Hello",
            api_key="gemini-secret",
            target_language="es",
            model="gemini-2.0-flash",
            timeout_s=7,
            chunk_chars=1000,
        )

    msg = str(exc.value)
    assert "api key not valid" in msg.lower()


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


def test_translate_text_groq_retries_on_missing_model(monkeypatch):
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

    out = tr.translate_text_groq(
        "Hello",
        api_key="gsk-secret",
        target_language="fr",
        model_candidates=["missing-groq-model", "llama-3.1-8b-instant"],
        timeout_s=9,
        chunk_chars=1000,
    )
    assert out == "Bonjour"
    assert calls[0]["model"] == "missing-groq-model"
    assert calls[1]["model"] == "llama-3.1-8b-instant"
    assert calls[0]["auth"] == "Bearer gsk-secret"
    assert str(calls[0]["url"] or "").startswith("https://api.groq.com/openai/v1/chat/completions")


def test_translate_text_dispatches_to_groq(monkeypatch):
    seen = {}

    def _fake_translate_text_groq(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_groq", _fake_translate_text_groq)
    out = tr.translate_text(
        "Hello",
        provider="groq",
        api_key="k",
        target_language="de",
        groq_model="llama-3.1-8b-instant",
    )
    assert out == "Translated"
    assert seen["kwargs"]["model"] == "llama-3.1-8b-instant"


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


def test_translate_text_openrouter_retries_on_missing_model(monkeypatch):
    calls = []

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append(
            {
                "url": url,
                "auth": (headers or {}).get("Authorization"),
                "referer": (headers or {}).get("HTTP-Referer"),
                "title": (headers or {}).get("X-Title"),
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
                    {"message": {"content": "Ciao"}},
                ]
            },
        )

    monkeypatch.setattr(tr.requests, "post", _fake_post)

    out = tr.translate_text_openrouter(
        "Hello",
        api_key="openrouter-secret",
        target_language="it",
        model_candidates=["missing-model", "openrouter/free"],
        timeout_s=8,
        chunk_chars=1000,
    )

    assert out == "Ciao"
    assert calls[0]["model"] == "missing-model"
    assert calls[1]["model"] == "openrouter/free"
    assert calls[0]["auth"] == "Bearer openrouter-secret"
    assert str(calls[0]["url"] or "").startswith("https://openrouter.ai/api/v1/chat/completions")
    assert calls[0]["referer"]
    assert calls[0]["title"]


def test_translate_text_dispatches_to_openrouter(monkeypatch):
    seen = {}

    def _fake_translate_text_openrouter(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return "Translated"

    monkeypatch.setattr(tr, "translate_text_openrouter", _fake_translate_text_openrouter)
    out = tr.translate_text(
        "Hello",
        provider="openrouter",
        api_key="k",
        target_language="de",
        openrouter_model="openrouter/free",
    )
    assert out == "Translated"
    assert seen["kwargs"]["model"] == "openrouter/free"


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


def test_translate_text_qwen_retries_across_region_endpoints(monkeypatch):
    calls = []
    endpoint_sequence = [
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    ]

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if "dashscope-intl" in url:
            return _Resp(
                403,
                payload={"error": {"message": "region not available for this api key"}},
                text='{"error":{"message":"region not available for this api key"}}',
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
        model="qwen-plus",
        timeout_s=6,
        chunk_chars=1000,
        endpoint_candidates=endpoint_sequence,
    )

    assert out == "Hallo"
    assert any("dashscope-intl" in c for c in calls)
    assert any("dashscope.aliyuncs.com" in c for c in calls)


def test_default_provider_model_candidates_include_current_recommended_options():
    openai_candidates = tuple(getattr(tr, "_DEFAULT_OPENAI_MODEL_CANDIDATES", ()))
    groq_candidates = tuple(getattr(tr, "_DEFAULT_GROQ_MODEL_CANDIDATES", ()))
    openrouter_candidates = tuple(getattr(tr, "_DEFAULT_OPENROUTER_MODEL_CANDIDATES", ()))
    gemini_candidates = tuple(getattr(tr, "_DEFAULT_GEMINI_MODEL_CANDIDATES", ()))
    qwen_candidates = tuple(getattr(tr, "_DEFAULT_QWEN_MODEL_CANDIDATES", ()))

    assert "gpt-5-mini" in openai_candidates
    assert "llama-3.1-8b-instant" in groq_candidates
    assert "openrouter/free" in openrouter_candidates
    assert "gemini-3-flash-preview" in gemini_candidates
    assert "qwen-mt-plus" in qwen_candidates


def test_list_openrouter_models_parses_model_ids(monkeypatch):
    class _ModelsResp:
        status_code = 200
        ok = True
        text = ""

        @staticmethod
        def json():
            return {
                "data": [
                    {"id": "openrouter/free"},
                    {"id": "google/gemma-3-4b-it:free"},
                    {"id": "openrouter/free"},
                    {"id": "openai/gpt-4.1-mini"},
                ]
            }

    def _fake_get(url, headers=None, timeout=None):
        assert str(url).startswith("https://openrouter.ai/api/v1/models")
        assert (headers or {}).get("Authorization") == "Bearer key123"
        return _ModelsResp()

    monkeypatch.setattr(tr.utils, "safe_requests_get", _fake_get)
    models = tr.list_openrouter_models(api_key="key123", timeout_s=12)

    assert models == [
        "google/gemma-3-4b-it:free",
        "openai/gpt-4.1-mini",
        "openrouter/free",
    ]
