import logging
from typing import Iterable, List

import requests

from core import utils

log = logging.getLogger(__name__)

_XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
_OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
_GEMINI_GENERATE_CONTENT_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Qwen (DashScope) OpenAI-compatible endpoint (international).
_QWEN_CHAT_COMPLETIONS_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

_DEFAULT_GROK_MODEL_CANDIDATES = (
    # Prefer fast non-reasoning models for translation latency/cost, then fall back.
    "grok-4-1-fast-non-reasoning",
    "grok-4-fast-non-reasoning",
    "grok-3-mini",
    "grok-4-1-fast-reasoning",
    "grok-4-fast-reasoning",
    "grok-4-0709",
    "grok-3",
    # Legacy aliases retained for older xAI API accounts/compatibility.
    "grok-4",
    "grok-beta",
)
_DEFAULT_OPENAI_MODEL_CANDIDATES = (
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "gpt-4.1-nano",
)
_DEFAULT_GEMINI_MODEL_CANDIDATES = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
_DEFAULT_QWEN_MODEL_CANDIDATES = (
    "qwen-plus",
    "qwen-plus-latest",
    "qwen3.5-plus",
    "qwen-turbo",
)
# Backward compatibility for existing callers/tests that still reference this name.
_DEFAULT_MODEL_CANDIDATES = _DEFAULT_GROK_MODEL_CANDIDATES
_DEFAULT_TIMEOUT_S = 45
_DEFAULT_CHUNK_CHARS = 3500
_MAX_TOTAL_CHARS = 50000


def _clean_target_language(target_language: str | None) -> str:
    value = str(target_language or "").strip()
    return value or "en"


def _iter_text_chunks(text: str, max_chars: int = _DEFAULT_CHUNK_CHARS) -> Iterable[str]:
    """Split text into translation-friendly chunks while preserving order."""
    s = str(text or "")
    if not s:
        return []

    try:
        max_chars = max(200, int(max_chars or _DEFAULT_CHUNK_CHARS))
    except Exception:
        max_chars = _DEFAULT_CHUNK_CHARS

    if len(s) <= max_chars:
        return [s]

    chunks: List[str] = []
    start = 0
    n = len(s)
    while start < n:
        end = min(n, start + max_chars)
        if end < n:
            # Prefer paragraph/newline boundaries for better translation continuity.
            split_at = s.rfind("\n\n", start, end)
            if split_at == -1:
                split_at = s.rfind("\n", start, end)
            if split_at == -1:
                split_at = s.rfind(" ", start, end)
            if split_at != -1 and split_at > start + 200:
                end = split_at
        chunk = s[start:end]
        if chunk:
            chunks.append(chunk)
        if end <= start:
            end = min(n, start + max_chars)
            if end <= start:
                break
        start = end
    return chunks


def _extract_chat_completion_text(payload: dict) -> str:
    try:
        choices = payload.get("choices") or []
        first = choices[0] if choices else {}
        msg = (first.get("message") or {})
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt:
                        parts.append(txt)
            if parts:
                return "".join(parts).strip()
    except Exception:
        pass
    return ""


def _error_message_text(value) -> str:
    if isinstance(value, dict):
        # xAI/OpenAI-style error envelopes may nest the useful text under error.message.
        for key in ("message", "error", "detail", "code", "type"):
            try:
                nested = _error_message_text(value.get(key))
            except Exception:
                nested = ""
            if nested:
                return nested
        try:
            return str(value)
        except Exception:
            return ""
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            txt = _error_message_text(item)
            if txt:
                parts.append(txt)
        return " ".join(parts)
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _retryable_model_error(resp: requests.Response | None, err_text: str = "") -> bool:
    if resp is not None:
        try:
            # Some xAI keys can see a model in the catalog but still get model-level
            # access denials (403) for a specific model. Retrying another candidate is safe.
            if int(getattr(resp, "status_code", 0) or 0) not in (400, 403, 404):
                return False
        except Exception:
            return False
        try:
            data = resp.json()
            msg = _error_message_text(data).lower()
            if "model" not in msg:
                return False
            return any(
                token in msg
                for token in (
                    "not found",
                    "unknown",
                    "invalid",
                    "unavailable",
                    "not available",
                    "unsupported",
                    "not allowed",
                    "not permitted",
                    "permission",
                    "access",
                    "entitled",
                    "tier",
                )
            )
        except Exception:
            pass
    txt = str(err_text or "").lower()
    if "model" not in txt:
        return False
    return any(
        token in txt
        for token in (
            "not found",
            "unknown",
            "invalid",
            "unavailable",
            "not available",
            "unsupported",
            "not allowed",
            "not permitted",
            "permission",
            "access",
            "entitled",
            "tier",
        )
    )


def _resolve_model_candidates(
    explicit_model: str | None,
    model_candidates: Iterable[str] | None,
    default_candidates: Iterable[str],
) -> list[str]:
    explicit = str(explicit_model or "").strip()
    if explicit:
        return [explicit]
    candidates = [str(m).strip() for m in (model_candidates or default_candidates) if str(m).strip()]
    if not candidates:
        candidates = [str(m).strip() for m in (default_candidates or ()) if str(m).strip()]
    return candidates


def _translate_chunk_chat_completions(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    default_candidates: Iterable[str],
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str,
    provider_label: str,
) -> str:
    api_key = str(api_key or "").strip()
    if not api_key:
        raise RuntimeError(f"Missing {provider_label} API key.")
    target_language = _clean_target_language(target_language)
    chunk = str(chunk or "")
    if not chunk:
        return ""

    headers = dict(utils.HEADERS)
    headers["Authorization"] = f"Bearer {api_key}"
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"

    candidates = _resolve_model_candidates(model, model_candidates, default_candidates)
    if not candidates:
        raise RuntimeError(f"No {provider_label} translation models configured.")

    system_prompt = (
        "You are a translation engine. Translate the user's text into the requested target language. "
        "Preserve line breaks, headings, and overall formatting. Return only the translated text with no commentary."
    )
    user_prompt = f"Target language: {target_language}\n\nText to translate:\n{chunk}"

    last_err = None
    for model_name in candidates:
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "stream": False,
                },
                timeout=max(5, int(timeout_s or _DEFAULT_TIMEOUT_S)),
            )
            if not getattr(resp, "ok", False):
                err_text = ""
                try:
                    err_text = resp.text or ""
                except Exception:
                    err_text = ""
                if _retryable_model_error(resp, err_text):
                    last_err = RuntimeError(f"{provider_label} model '{model_name}' unavailable")
                    continue
                try:
                    resp.raise_for_status()
                except Exception as e:
                    raise RuntimeError(str(e) or "Translation request failed") from e

            data = resp.json() if resp is not None else {}
            translated = _extract_chat_completion_text(data)
            if translated:
                return translated
            raise RuntimeError(f"{provider_label} returned an empty translation response.")
        except Exception as e:
            last_err = e
            if _retryable_model_error(getattr(e, "response", None), str(e)):
                continue
            break

    raise RuntimeError(str(last_err) or f"{provider_label} translation failed")


def _extract_gemini_completion_text(payload: dict) -> str:
    try:
        candidates = payload.get("candidates") or []
        first = candidates[0] if candidates else {}
        content = first.get("content") or {}
        parts = content.get("parts") or []
        out = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            txt = part.get("text")
            if isinstance(txt, str) and txt:
                out.append(txt)
        if out:
            return "".join(out).strip()
    except Exception:
        pass
    return ""


def _translate_chunk_grok(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str = _XAI_CHAT_COMPLETIONS_URL,
) -> str:
    return _translate_chunk_chat_completions(
        chunk,
        api_key=api_key,
        target_language=target_language,
        model=model,
        model_candidates=model_candidates,
        default_candidates=_DEFAULT_GROK_MODEL_CANDIDATES,
        timeout_s=timeout_s,
        endpoint=endpoint,
        provider_label="Grok",
    )


def _translate_chunk_openai(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str = _OPENAI_CHAT_COMPLETIONS_URL,
) -> str:
    return _translate_chunk_chat_completions(
        chunk,
        api_key=api_key,
        target_language=target_language,
        model=model,
        model_candidates=model_candidates,
        default_candidates=_DEFAULT_OPENAI_MODEL_CANDIDATES,
        timeout_s=timeout_s,
        endpoint=endpoint,
        provider_label="OpenAI",
    )


def _translate_chunk_gemini(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint_template: str = _GEMINI_GENERATE_CONTENT_URL_TEMPLATE,
) -> str:
    api_key = str(api_key or "").strip()
    if not api_key:
        raise RuntimeError("Missing Gemini API key.")
    target_language = _clean_target_language(target_language)
    chunk = str(chunk or "")
    if not chunk:
        return ""

    headers = dict(utils.HEADERS)
    headers["x-goog-api-key"] = api_key
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"

    candidates = _resolve_model_candidates(model, model_candidates, _DEFAULT_GEMINI_MODEL_CANDIDATES)
    if not candidates:
        raise RuntimeError("No Gemini translation models configured.")

    prompt = (
        "Translate this text into the target language.\n"
        "Preserve line breaks, headings, and overall formatting.\n"
        "Return only translated text with no commentary.\n\n"
        f"Target language: {target_language}\n\n"
        f"Text to translate:\n{chunk}"
    )

    last_err = None
    for model_name in candidates:
        try:
            endpoint = str(endpoint_template or _GEMINI_GENERATE_CONTENT_URL_TEMPLATE).format(model=model_name)
            resp = requests.post(
                endpoint,
                headers=headers,
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0,
                    },
                },
                timeout=max(5, int(timeout_s or _DEFAULT_TIMEOUT_S)),
            )
            if not getattr(resp, "ok", False):
                err_text = ""
                try:
                    err_text = resp.text or ""
                except Exception:
                    err_text = ""
                if _retryable_model_error(resp, err_text):
                    last_err = RuntimeError(f"Gemini model '{model_name}' unavailable")
                    continue
                try:
                    resp.raise_for_status()
                except Exception as e:
                    raise RuntimeError(str(e) or "Translation request failed") from e

            data = resp.json() if resp is not None else {}
            translated = _extract_gemini_completion_text(data)
            if translated:
                return translated
            raise RuntimeError("Gemini returned an empty translation response.")
        except Exception as e:
            last_err = e
            if _retryable_model_error(getattr(e, "response", None), str(e)):
                continue
            break
    raise RuntimeError(str(last_err) or "Gemini translation failed")


def _translate_chunk_qwen(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str = _QWEN_CHAT_COMPLETIONS_URL,
) -> str:
    return _translate_chunk_chat_completions(
        chunk,
        api_key=api_key,
        target_language=target_language,
        model=model,
        model_candidates=model_candidates,
        default_candidates=_DEFAULT_QWEN_MODEL_CANDIDATES,
        timeout_s=timeout_s,
        endpoint=endpoint,
        provider_label="Qwen",
    )


def translate_text_grok(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str = _XAI_CHAT_COMPLETIONS_URL,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw

    # Avoid accidentally sending extremely large content in a single UI action.
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_grok(
                chunk,
                api_key=api_key,
                target_language=target_language,
                model=model,
                model_candidates=model_candidates,
                timeout_s=timeout_s,
                endpoint=endpoint,
            )
        )
    return "".join(translated_chunks)


def translate_text_openai(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str = _OPENAI_CHAT_COMPLETIONS_URL,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_openai(
                chunk,
                api_key=api_key,
                target_language=target_language,
                model=model,
                model_candidates=model_candidates,
                timeout_s=timeout_s,
                endpoint=endpoint,
            )
        )
    return "".join(translated_chunks)


def translate_text_gemini(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint_template: str = _GEMINI_GENERATE_CONTENT_URL_TEMPLATE,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_gemini(
                chunk,
                api_key=api_key,
                target_language=target_language,
                model=model,
                model_candidates=model_candidates,
                timeout_s=timeout_s,
                endpoint_template=endpoint_template,
            )
        )
    return "".join(translated_chunks)


def translate_text_qwen(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str = _QWEN_CHAT_COMPLETIONS_URL,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_qwen(
                chunk,
                api_key=api_key,
                target_language=target_language,
                model=model,
                model_candidates=model_candidates,
                timeout_s=timeout_s,
                endpoint=endpoint,
            )
        )
    return "".join(translated_chunks)


def translate_text(
    text: str,
    *,
    provider: str,
    api_key: str,
    target_language: str,
    grok_model: str | None = None,
    openai_model: str | None = None,
    gemini_model: str | None = None,
    qwen_model: str | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
) -> str:
    prov = str(provider or "").strip().lower()
    if prov == "grok":
        return translate_text_grok(
            text,
            api_key=api_key,
            target_language=target_language,
            model=grok_model,
            timeout_s=timeout_s,
            chunk_chars=chunk_chars,
        )
    if prov == "openai":
        return translate_text_openai(
            text,
            api_key=api_key,
            target_language=target_language,
            model=openai_model,
            timeout_s=timeout_s,
            chunk_chars=chunk_chars,
        )
    if prov == "gemini":
        return translate_text_gemini(
            text,
            api_key=api_key,
            target_language=target_language,
            model=gemini_model,
            timeout_s=timeout_s,
            chunk_chars=chunk_chars,
        )
    if prov == "qwen":
        return translate_text_qwen(
            text,
            api_key=api_key,
            target_language=target_language,
            model=qwen_model,
            timeout_s=timeout_s,
            chunk_chars=chunk_chars,
        )
    raise RuntimeError(f"Unsupported translation provider: {provider}")
