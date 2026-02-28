"""Shared OpenAI chat client for GPT (search answer, doc metadata, rephrase, categorize)."""
from __future__ import annotations

import json
import logging
import os
import time
from types import SimpleNamespace

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# #region agent log
def _debug_log(data: dict) -> None:
    try:
        log_path = os.path.join(os.getcwd(), "debug-697fbd.log")
        payload = {"sessionId": "697fbd", "timestamp": int(time.time() * 1000), "location": "openai_client.py", "message": "GPT request", "data": data, "hypothesisId": "H1"}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        logger.warning("Debug log write failed: %s", e)
# #endregion


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
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if model and getattr(settings, "openai_send_model_in_body", True):
        body["model"] = model
    if kwargs.get("response_format") and settings.openai_use_json_mode:
        body["response_format"] = kwargs["response_format"]

    _log_request(body, url)

    # #region agent log
    try:
        body_keys = list(body.keys())
        body_json = json.dumps(body)
        _debug_log({"body_keys": body_keys, "openai_use_json_mode": getattr(settings, "openai_use_json_mode", None), "has_response_format": "response_format" in body, "body_json_length": len(body_json), "body_sample": body_json[:2000]})
    except Exception:
        pass
    # #endregion

    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json=body, headers=headers)

    # #region agent log
    try:
        _debug_log({"response_status": r.status_code, "response_body_preview": r.text[:1500] if r.status_code >= 400 else None})
    except Exception:
        pass
    # #endregion

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
