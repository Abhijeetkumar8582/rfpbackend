"""Middleware to log each API request to endpoint_logs."""
import asyncio
import json
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.database import SessionLocal
from app.services.logging_service import log_endpoint
from app.core.security import decode_token


# Paths we do not log (health checks, etc.)
SKIP_PATHS = {"/health"}
MAX_BODY_LOG_BYTES = 64 * 1024  # 64 KB


def _get_actor_from_request(request: Request) -> str | None:
    """Extract user id from JWT if present."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    return payload.get("sub")


def _ensure_str(v) -> str:
    """Coerce value to str for JSON/DB (MySQL-safe)."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _sanitize_headers(headers: dict) -> str | None:
    """Serialize headers as JSON, redacting Authorization value. All values as str for MySQL."""
    if not headers:
        return None
    out = {}
    for k, v in headers.items():
        key = _ensure_str(k)
        val = "Bearer ***" if key.lower() == "authorization" else _ensure_str(v)
        out[key] = val
    try:
        return json.dumps(out, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _body_for_log(body_bytes: bytes) -> str | None:
    """Truncate and decode body for storage."""
    if not body_bytes:
        return None
    if len(body_bytes) > MAX_BODY_LOG_BYTES:
        body_bytes = body_bytes[:MAX_BODY_LOG_BYTES]
    try:
        return body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None


def _response_headers_for_log(headers) -> str | None:
    """Serialize response headers as JSON. All values as str for MySQL."""
    if not headers:
        return None
    try:
        out = {_ensure_str(k): _ensure_str(v) for k, v in dict(headers).items()}
        return json.dumps(out, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _log_sync(
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    actor_user_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
    error_message: str | None,
    query_string: str | None,
    request_headers: str | None,
    request_body: str | None,
    response_headers: str | None,
    response_body: str | None,
) -> None:
    """Synchronous DB write (run in thread to avoid blocking event loop)."""
    db = SessionLocal()
    try:
        log_endpoint(
            db,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=error_message,
            query_string=query_string,
            request_headers=request_headers,
            request_body=request_body,
            response_headers=response_headers,
            response_body=response_body,
        )
    except Exception:
        pass  # Don't fail the request if logging fails (e.g. missing table)
    finally:
        db.close()


class EndpointLogMiddleware(BaseHTTPMiddleware):
    """Log each request to endpoint_logs after response is ready."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        path = request.url.path or ""
        method = request.method or "GET"
        query_string = request.url.query or None
        if query_string and len(query_string) > 2048:
            query_string = query_string[:2048]
        headers_dict = dict(request.headers) if request.headers else {}
        request_headers_json = _sanitize_headers(headers_dict)

        send = getattr(request, "_send", None) or getattr(request, "send", None)
        body_bytes = b""
        request_body_str = None
        if send is not None:
            try:
                body_bytes = await request.body()
                request_body_str = _body_for_log(body_bytes)
            except Exception:
                pass
            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            new_request = Request(scope=request.scope, receive=receive, send=send)
        else:
            new_request = request

        start = time.perf_counter()
        response = await call_next(new_request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Capture response body and headers (replay body so client still receives it)
        response_body_chunks = []
        try:
            async for chunk in response.body_iterator:
                response_body_chunks.append(chunk)
        except Exception:
            pass
        response_body_bytes = b"".join(response_body_chunks)
        response_body_str = _body_for_log(response_body_bytes)

        async def replay_body():
            for chunk in response_body_chunks:
                yield chunk
        response.body_iterator = replay_body()

        response_headers_json = _response_headers_for_log(response.headers)

        actor = _get_actor_from_request(request)
        forwarded = request.headers.get("X-Forwarded-For")
        ip = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        error_message = None
        if response.status_code >= 400:
            error_message = f"HTTP {response.status_code}"

        await asyncio.to_thread(
            _log_sync,
            method,
            path,
            response.status_code,
            duration_ms,
            actor,
            ip,
            user_agent,
            error_message,
            query_string,
            request_headers_json,
            request_body_str,
            response_headers_json,
            response_body_str,
        )
        return response
