import logging
from typing import Iterable, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from core import utils

log = logging.getLogger(__name__)

_XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
_GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
_OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
_OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_APP_REFERER = "https://github.com/serrebi/BlindRSS"
_OPENROUTER_APP_TITLE = "BlindRSS"
_GEMINI_GENERATE_CONTENT_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Qwen (DashScope) OpenAI-compatible endpoint (international).
_QWEN_CHAT_COMPLETIONS_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
_QWEN_CHAT_COMPLETIONS_ENDPOINTS = (
    # International (Singapore)
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    # China mainland (Beijing)
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    # United States (Virginia)
    "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions",
)

_DEFAULT_GROK_MODEL_CANDIDATES = (
    # Prefer fast non-reasoning models for translation latency/cost, then fall back.
    "grok-4-1-fast-non-reasoning",
    "grok-4-fast-non-reasoning",
    "grok-3-mini",
    "grok-4-1-fast-reasoning",
    "grok-4-fast-reasoning",
    "grok-4-0709",
    "grok-3-fast",
    "grok-3",
    # Legacy aliases retained for older xAI API accounts/compatibility.
    "grok-4",
    "grok-beta",
)
_DEFAULT_OPENAI_MODEL_CANDIDATES = (
    "gpt-5-mini",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "gpt-4.1-nano",
)
_DEFAULT_GROQ_MODEL_CANDIDATES = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
)
_DEFAULT_OPENROUTER_MODEL_CANDIDATES = (
    # Start with free routing for zero-cost testing, then fall back to auto routing.
    "openrouter/free",
    "openrouter/auto",
)
_DEFAULT_GEMINI_MODEL_CANDIDATES = (
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
_DEFAULT_QWEN_MODEL_CANDIDATES = (
    # Translation-specialized models.
    "qwen-mt-plus",
    "qwen-mt-flash",
    "qwen-mt-lite",
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


def _resolve_endpoint_candidates(
    explicit_endpoint: str | None,
    endpoint_candidates: Iterable[str] | None,
    default_candidates: Iterable[str],
) -> list[str]:
    explicit = str(explicit_endpoint or "").strip()
    if endpoint_candidates is not None:
        candidates = [str(m).strip() for m in endpoint_candidates if str(m).strip()]
        if explicit and explicit not in candidates:
            candidates.insert(0, explicit)
        return candidates
    if explicit:
        return [explicit]
    return [str(m).strip() for m in (default_candidates or ()) if str(m).strip()]


def _append_query_param(url: str, name: str, value: str) -> str:
    raw_url = str(url or "").strip()
    if not raw_url or not name:
        return raw_url
    parts = urlsplit(raw_url)
    query_pairs = []
    try:
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    except Exception:
        query_pairs = []
    key_lower = str(name).lower()
    query_pairs = [(k, v) for (k, v) in query_pairs if str(k).lower() != key_lower]
    query_pairs.append((str(name), str(value or "")))
    new_query = urlencode(query_pairs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _response_error_detail(resp: requests.Response | None) -> str:
    if resp is None:
        return ""
    code = 0
    try:
        code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        code = 0

    msg = ""
    try:
        msg = _error_message_text(resp.json())
    except Exception:
        msg = ""
    if not msg:
        try:
            msg = str(resp.text or "").strip()
        except Exception:
            msg = ""
    if msg:
        msg = " ".join(str(msg).split())
        if len(msg) > 260:
            msg = msg[:257].rstrip() + "..."

    if code and msg:
        return f"HTTP {code}: {msg}"
    if code:
        return f"HTTP {code}"
    return msg


def _openrouter_extra_headers() -> dict:
    extra = {}
    referer = str(_OPENROUTER_APP_REFERER or "").strip()
    title = str(_OPENROUTER_APP_TITLE or "").strip()
    if referer:
        extra["HTTP-Referer"] = referer
    if title:
        extra["X-Title"] = title
    return extra


def _looks_like_groq_key(api_key: str | None) -> bool:
    key = str(api_key or "").strip().lower()
    return bool(key.startswith("gsk_"))


def list_openrouter_models(api_key: str | None = None, timeout_s: int = 20) -> list[str]:
    headers = dict(utils.HEADERS)
    headers["Accept"] = "application/json"
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(_openrouter_extra_headers())
    try:
        timeout = max(5, min(60, int(timeout_s or 20)))
    except Exception:
        timeout = 20

    try:
        resp = utils.safe_requests_get(
            _OPENROUTER_MODELS_URL,
            headers=headers,
            timeout=timeout,
        )
    except Exception as e:
        raise RuntimeError(f"OpenRouter models request failed: {e}") from e

    if not getattr(resp, "ok", False):
        detail = _response_error_detail(resp)
        if detail:
            raise RuntimeError(f"OpenRouter models request failed ({detail})")
        raise RuntimeError("OpenRouter models request failed")

    try:
        payload = resp.json() if resp is not None else {}
    except Exception as e:
        raise RuntimeError(f"OpenRouter models response was not valid JSON: {e}") from e

    models = []
    try:
        for item in (payload.get("data") or []):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                models.append(model_id)
    except Exception:
        models = []

    # Keep deterministic ordering in the UI and remove duplicates.
    out = []
    seen = set()
    for model_id in sorted(models, key=lambda v: str(v).lower()):
        key_id = str(model_id).lower()
        if key_id in seen:
            continue
        seen.add(key_id)
        out.append(str(model_id))
    return out


def _gemini_empty_response_reason(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    try:
        prompt_feedback = payload.get("promptFeedback")
    except Exception:
        prompt_feedback = None
    detail = _error_message_text(prompt_feedback)
    if detail:
        return detail
    try:
        candidates = payload.get("candidates") or []
        first = candidates[0] if candidates else {}
    except Exception:
        first = {}
    detail = _error_message_text(first.get("finishReason"))
    if detail:
        return detail
    detail = _error_message_text(first.get("safetyRatings"))
    if detail:
        return detail
    return ""


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
    extra_headers: dict | None = None,
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
    if isinstance(extra_headers, dict):
        for key, value in extra_headers.items():
            k = str(key or "").strip()
            v = str(value or "").strip()
            if not k or not v:
                continue
            headers[k] = v

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
                detail = _response_error_detail(resp)
                if detail:
                    raise RuntimeError(f"{provider_label} request failed ({detail})")
                raise RuntimeError(f"{provider_label} request failed")

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
    if _looks_like_groq_key(api_key):
        # Compatibility fallback: users often confuse Groq and Grok keys.
        # If a Groq key is entered while Grok is selected, route it to Groq.
        return _translate_chunk_groq(
            chunk,
            api_key=api_key,
            target_language=target_language,
            model=model,
            model_candidates=model_candidates,
            timeout_s=timeout_s,
        )
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


def _translate_chunk_groq(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str = _GROQ_CHAT_COMPLETIONS_URL,
) -> str:
    return _translate_chunk_chat_completions(
        chunk,
        api_key=api_key,
        target_language=target_language,
        model=model,
        model_candidates=model_candidates,
        default_candidates=_DEFAULT_GROQ_MODEL_CANDIDATES,
        timeout_s=timeout_s,
        endpoint=endpoint,
        provider_label="Groq",
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


def _translate_chunk_openrouter(
    chunk: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    endpoint: str = _OPENROUTER_CHAT_COMPLETIONS_URL,
) -> str:
    return _translate_chunk_chat_completions(
        chunk,
        api_key=api_key,
        target_language=target_language,
        model=model,
        model_candidates=model_candidates,
        default_candidates=_DEFAULT_OPENROUTER_MODEL_CANDIDATES,
        timeout_s=timeout_s,
        endpoint=endpoint,
        provider_label="OpenRouter",
        extra_headers=_openrouter_extra_headers(),
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
            endpoint = _append_query_param(endpoint, "key", api_key)
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
                detail = _response_error_detail(resp)
                if detail:
                    raise RuntimeError(f"Gemini request failed ({detail})")
                raise RuntimeError("Gemini request failed")

            data = resp.json() if resp is not None else {}
            translated = _extract_gemini_completion_text(data)
            if translated:
                return translated
            empty_reason = _gemini_empty_response_reason(data)
            if empty_reason:
                raise RuntimeError(f"Gemini returned an empty translation response ({empty_reason})")
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
    endpoint: str | None = None,
    endpoint_candidates: Iterable[str] | None = None,
) -> str:
    endpoints = _resolve_endpoint_candidates(
        endpoint,
        endpoint_candidates,
        _QWEN_CHAT_COMPLETIONS_ENDPOINTS,
    )
    if not endpoints:
        endpoints = [str(_QWEN_CHAT_COMPLETIONS_URL)]

    last_err = None
    for endpoint_url in endpoints:
        try:
            return _translate_chunk_chat_completions(
                chunk,
                api_key=api_key,
                target_language=target_language,
                model=model,
                model_candidates=model_candidates,
                default_candidates=_DEFAULT_QWEN_MODEL_CANDIDATES,
                timeout_s=timeout_s,
                endpoint=endpoint_url,
                provider_label="Qwen",
            )
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(str(last_err) or "Qwen translation failed")


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


def translate_text_groq(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str = _GROQ_CHAT_COMPLETIONS_URL,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_groq(
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


def translate_text_openrouter(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str = _OPENROUTER_CHAT_COMPLETIONS_URL,
) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if len(raw) > _MAX_TOTAL_CHARS:
        raw = raw[:_MAX_TOTAL_CHARS]

    translated_chunks: List[str] = []
    for chunk in _iter_text_chunks(raw, max_chars=chunk_chars):
        translated_chunks.append(
            _translate_chunk_openrouter(
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


def translate_text_qwen(
    text: str,
    *,
    api_key: str,
    target_language: str,
    model: str | None = None,
    model_candidates: Iterable[str] | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    endpoint: str | None = None,
    endpoint_candidates: Iterable[str] | None = None,
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
                endpoint_candidates=endpoint_candidates,
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
    groq_model: str | None = None,
    openai_model: str | None = None,
    openrouter_model: str | None = None,
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
    if prov == "groq":
        return translate_text_groq(
            text,
            api_key=api_key,
            target_language=target_language,
            model=groq_model,
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
    if prov == "openrouter":
        return translate_text_openrouter(
            text,
            api_key=api_key,
            target_language=target_language,
            model=openrouter_model,
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
