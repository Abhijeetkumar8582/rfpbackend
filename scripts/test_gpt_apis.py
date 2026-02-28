"""Direct GPT API tests — call Druid/OpenAI chat completions endpoint from this script."""
import json
import os
import sys

# Run from backend/ so .env is found
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
os.chdir(BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv()

import requests

# From .env: full URL (e.g. .../chat/completions?api-version=2024-06-01) and Bearer token
GPT_URL = os.environ.get("OPENAI_BASE_URL", "").strip()
GPT_TOKEN = os.environ.get("OPENAI_API_KEY", "").strip()
GPT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def print_request(method: str, url: str, body: dict | None = None, headers: dict | None = None):
    """Print the API request (method, URL, headers, body)."""
    print("--- Request ---")
    print(f"  {method} {url}")
    if headers:
        for k, v in headers.items():
            print(f"  {k}: {v}")
    if body is not None:
        print("  body:", json.dumps(body, indent=2))
    print("---------------")
    sys.stdout.flush()


def gpt_chat(messages: list[dict], max_tokens: int = 1024) -> tuple[bool, str]:
    """
    Call GPT chat completions API directly.
    messages: list of {"role": "system"|"user"|"assistant", "content": "..."}
    Returns (success, response_text or error_message).
    """
    if not GPT_URL or not GPT_TOKEN:
        return False, "Set OPENAI_BASE_URL and OPENAI_API_KEY in .env"

    headers = {
        "Authorization": f"Bearer {GPT_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
    }
    print_request("POST", GPT_URL, body=body, headers=headers)
    r = requests.post(GPT_URL, json=body, headers=headers, timeout=60)
    print(f"  Status: {r.status_code}")
    if not r.ok:
        print(f"  Error: {r.text[:500]}")
        return False, r.text[:500]
    data = r.json()
    choice = (data.get("choices") or [None])[0]
    if not choice:
        return False, "No choices in response"
    content = (choice.get("message") or {}).get("content") or ""
    print("  Response:", content[:500] + ("..." if len(content) > 500 else ""))
    return True, content


def test_simple_chat():
    """Direct GPT call: single user message."""
    print("\n[1] Direct GPT — simple chat\n")
    ok, text = gpt_chat([
        {"role": "user", "content": "Reply in one sentence: What is the main benefit of microservices?"},
    ])
    return ok


def test_rephrase_style():
    """Direct GPT call: system + user (rephrase-style prompt)."""
    print("\n[2] Direct GPT — rephrase-style (system + user)\n")
    ok, text = gpt_chat([
        {"role": "system", "content": "You are an expert technical writer. Rephrase the given answer in a more technical way. Output only the rephrased answer."},
        {"role": "user", "content": "Question: What is the main benefit of microservices?\n\nAnswer: You can change one part without breaking the rest and scale parts separately."},
    ])
    return ok


if __name__ == "__main__":
    print("Direct GPT API tests (uses OPENAI_BASE_URL + OPENAI_API_KEY from .env)")
    if not GPT_URL or not GPT_TOKEN:
        print("ERROR: OPENAI_BASE_URL and OPENAI_API_KEY must be set in backend/.env")
        sys.exit(1)
    ok = 0
    ok += test_simple_chat()
    ok += test_rephrase_style()
    print(f"\nPassed: {ok}/2")
    sys.exit(0 if ok == 2 else 1)
