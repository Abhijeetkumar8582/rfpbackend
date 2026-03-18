"""Shared OpenAI chat client for GPT (search answer, doc metadata, rephrase, categorize)."""
from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model-specific request parameter handling
# ---------------------------------------------------------------------------

_MODEL_PROFILES: list[tuple[re.Pattern[str], dict]] = [
    # Reasoning-style models often use max_completion_tokens and may reject temperature.
    (re.compile(r"^(o1|o3)(-|$)", re.IGNORECASE), {"token_key": "max_completion_tokens", "supports_temperature": False}),
    (re.compile(r"reasoning", re.IGNORECASE), {"token_key": "max_completion_tokens", "supports_temperature": False}),
    # Default GPT-family chat models.
    (re.compile(r"^gpt-", re.IGNORECASE), {"token_key": "max_tokens", "supports_temperature": True}),
]


def _model_profile(model: str | None) -> dict:
    m = (model or "").strip()
    if not m:
        return {"token_key": "max_tokens", "supports_temperature": True}
    for pat, prof in _MODEL_PROFILES:
        if pat.search(m):
            return prof
    return {"token_key": "max_tokens", "supports_temperature": True}


def _apply_model_params(body: dict, model: str | None, *, max_tokens: int | None, temperature: float | None) -> None:
    prof = _model_profile(model)
    token_key = prof.get("token_key") or "max_tokens"
    supports_temperature = bool(prof.get("supports_temperature", True))

    # Token parameter name varies by model families / gateways.
    if max_tokens is not None:
        body[token_key] = int(max_tokens)

    # Some models/gateways reject temperature; omit if unsupported.
    if temperature is not None and supports_temperature:
        body["temperature"] = float(temperature)


def build_chat_completions_body(
    *,
    model: str | None,
    messages: list[dict],
    max_tokens: int | None = None,
    temperature: float | None = None,
    response_format: dict | None = None,
    send_model_in_body: bool = True,
) -> dict:
    """
    Build an OpenAI-compatible chat-completions request body, applying model-specific
    parameter differences (e.g. max_tokens vs max_completion_tokens, temperature support).
    """
    body: dict = {"messages": messages}
    if model and send_model_in_body:
        body["model"] = model
    _apply_model_params(body, model, max_tokens=max_tokens, temperature=temperature)
    if response_format is not None:
        body["response_format"] = response_format
    return body


def _log_request(body: dict, url: str):
    """Log outgoing OpenAI API request (URL, body) to logger and console for debugging."""
    try:
        body_str = json.dumps(body, indent=2)
        # Console debug: full request so we can debug 503 / GPT failures
        print("\n" + "=" * 60)
        print("DEBUG GPT REQUEST")
        print("=" * 60)
        print(f"POST {url}")
        print("Body (full):")
        print(body_str)
        print("=" * 60 + "\n")
        # Logger: truncated for log volume
        logger.info("OpenAI API request: POST %s body_len=%d", url, len(body_str))
        logger.debug("OpenAI API body: %s", body_str[:2000])
    except Exception as e:
        logger.warning("Failed to log request: %s", e)


def _chat_completions_post(messages: list[dict], max_tokens: int = 1024, model: str | None = None, **kwargs) -> SimpleNamespace:
    """
    Call GPT chat completions. Matches:
      curl -X POST "$OPENAI_BASE_URL" \\
        -H "Authorization: Bearer $OPENAI_API_KEY" \\
        -H "Content-Type: application/json" \\
        -d '{"model": "...", "messages": [...], "max_tokens": 1024}'
    Optional: response_format added when openai_use_json_mode is True and caller passes it.
    Some gateways (e.g. Druid/Azure) expect "model" in the body.
    """
    url = (settings.openai_base_url or "").strip()
    token = (settings.openai_api_key or "").strip()
    if not url or not token:
        raise RuntimeError("OPENAI_BASE_URL and OPENAI_API_KEY are required for GPT.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = build_chat_completions_body(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=kwargs.get("temperature"),
        response_format=(kwargs.get("response_format") if settings.openai_use_json_mode else None),
        send_model_in_body=bool(getattr(settings, "openai_send_model_in_body", True)),
    )

    _log_request(body, url)

    timeout = float(kwargs.get("timeout", 60.0) or 60.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body, headers=headers)

    # Debug: print response status so 503 is visible in console
    print(f"DEBUG GPT RESPONSE: status={r.status_code}")
    if r.status_code >= 400:
        err_preview = r.text[:1500] if r.text else ""
        print(f"DEBUG GPT RESPONSE BODY: {err_preview}")
        # Surface gateway error (e.g. 400) so caller can return it in 503 detail
        raise RuntimeError(f"GPT gateway returned {r.status_code}: {err_preview}")
    r.raise_for_status()
    data = r.json()
    choice = (data.get("choices") or [None])[0]
    if not choice:
        raise RuntimeError("No choices in response")
    message = (choice.get("message") or {}).get("content") or ""

    # Return object compatible with resp.choices[0].message.content
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=message),
            )
        ]
    )


class _ChatCompletions:
    def create(self, model=None, messages=None, max_tokens=1024, **kwargs):
        return _chat_completions_post(messages=messages, max_tokens=max_tokens, model=model, **kwargs)


class _Chat:
    completions = _ChatCompletions()


class _OpenAIWrapper:
    """Wrapper that matches OpenAI client.chat.completions.create() using same request format as test_gpt_apis."""
    chat = _Chat()


def get_chat_client():
    """
    Return (client wrapper, model name) for chat completions.
    Uses OPENAI_BASE_URL and OPENAI_API_KEY with same request format as test_gpt_apis.py:
    POST to full URL, body {"messages": ..., "max_tokens": ...}.
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for GPT.")
    if not (settings.openai_base_url or "").strip():
        raise RuntimeError("OPENAI_BASE_URL is required for GPT.")
    return _OpenAIWrapper(), settings.openai_chat_model
