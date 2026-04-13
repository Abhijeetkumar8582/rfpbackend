#!/usr/bin/env python3
"""
Hit a running RFP backend to verify routes respond (optional login).

Usage (server must be up, e.g. uvicorn app.main:app --reload):

  cd backend
  set PYTHONPATH=%CD%
  python scripts/smoke_test_api.py
  python scripts/smoke_test_api.py --base-url http://127.0.0.1:8000

Optional login (real user in DB):

  set SMOKE_EMAIL=you@example.com
  set SMOKE_PASSWORD=secret
  python scripts/smoke_test_api.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _get(url: str, timeout: float = 15.0) -> tuple[int, dict[str, Any] | str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def _post_json(url: str, payload: dict, timeout: float = 30.0) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def main() -> int:
    p = argparse.ArgumentParser(description="Smoke-test RFP API (running server).")
    p.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000"), help="API root")
    args = p.parse_args()
    base = args.base_url.rstrip("/")

    ok = True

    code, data = _get(f"{base}/health")
    if code != 200 or (isinstance(data, dict) and data.get("status") != "ok"):
        print(f"FAIL /health -> {code} {data!r}")
        ok = False
    else:
        print(f"OK   /health -> {data}")

    code, data = _get(f"{base}/openapi.json")
    if code != 200 or not isinstance(data, dict) or "paths" not in data:
        print(f"FAIL /openapi.json -> {code}")
        ok = False
    else:
        paths = list(data.get("paths", {}).keys())[:5]
        print(f"OK   /openapi.json ({len(data.get('paths', {}))} paths), sample: {paths}")

    code, data = _post_json(
        f"{base}/api/v1/auth/login",
        {"email": "invalid_smoke@example.com", "password": "x"},
    )
    if code != 401:
        print(f"FAIL login with bad user should be 401, got {code} {data!r}")
        ok = False
    else:
        print(f"OK   POST /api/v1/auth/login (invalid) -> 401")

    email = (os.environ.get("SMOKE_EMAIL") or "").strip()
    password = (os.environ.get("SMOKE_PASSWORD") or "").strip()
    if email and password:
        code, data = _post_json(
            f"{base}/api/v1/auth/login",
            {"email": email, "password": password},
        )
        if code != 200 or not isinstance(data, dict) or not data.get("access_token"):
            print(f"FAIL login with SMOKE_EMAIL -> {code} {data!r}")
            ok = False
        else:
            token = data["access_token"]
            print(f"OK   POST /api/v1/auth/login (SMOKE_*) -> 200, token len={len(token)}")
            # Optional: authenticated search (may 503 if OpenAI/Qdrant not configured)
            project_id = (os.environ.get("SMOKE_PROJECT_ID") or "PROJ-2026-001").strip()
            req = urllib.request.Request(
                f"{base}/api/v1/search/answer",
                data=json.dumps(
                    {"query_text": "hello", "project_id": project_id, "k": 2},
                ).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    print(f"OK   POST /api/v1/search/answer -> {resp.status} (body len={len(body)})")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                print(
                    f"INFO POST /api/v1/search/answer -> {e.code} "
                    f"(embeddings/Qdrant/OpenAI may be unset: {err_body[:300]})",
                )
    else:
        print("SKIP login+search (set SMOKE_EMAIL and SMOKE_PASSWORD to test authenticated routes)")

    if ok:
        print("\nSmoke test finished: basic checks passed.")
        return 0
    print("\nSmoke test finished: some checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
