"""Start/stop a local Qdrant process when the backend manages it (localhost only)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_proc: subprocess.Popen | None = None
_started_by_us: bool = False


def _local_hosts() -> frozenset[str]:
    return frozenset({"localhost", "127.0.0.1", "::1"})


def _base_url() -> str:
    return (settings.qdrant_url or "http://127.0.0.1:6333").rstrip("/")


def should_manage_qdrant() -> bool:
    # Embedded path mode (QdrantClient(path=...)) — no separate server to spawn.
    if (settings.qdrant_local_path or "").strip():
        return False
    if not settings.qdrant_auto_start:
        return False
    try:
        u = urlparse(_base_url())
    except Exception:
        return False
    host = (u.hostname or "").lower()
    return host in _local_hosts()


def _health_ok() -> bool:
    url = f"{_base_url()}/readyz"
    headers: dict[str, str] = {}
    if (settings.qdrant_api_key or "").strip():
        headers["api-key"] = (settings.qdrant_api_key or "").strip()
    try:
        r = httpx.get(url, headers=headers, timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _find_qdrant_binary() -> str | None:
    raw = (settings.qdrant_binary_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return str(p)
        logger.warning("QDRANT_BINARY_PATH set but file not found: %s", p)
    for name in ("qdrant", "qdrant.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _storage_dir() -> Path:
    raw = (settings.qdrant_storage_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = _BACKEND_ROOT / p
    else:
        p = _BACKEND_ROOT / ".qdrant_storage"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _http_port() -> int:
    try:
        u = urlparse(_base_url())
        if u.port:
            return int(u.port)
    except Exception:
        pass
    return 6333


def start_qdrant_if_configured() -> None:
    """If configured for local management and Qdrant is not up, spawn the binary and wait for /readyz."""
    global _proc, _started_by_us

    if not should_manage_qdrant():
        return

    if _health_ok():
        logger.info("Qdrant already reachable at %s", _base_url())
        return

    binary = _find_qdrant_binary()
    if not binary:
        logger.warning(
            "QDRANT_AUTO_START is enabled but no Qdrant executable was found. "
            "Install Qdrant, add it to PATH, or set QDRANT_BINARY_PATH in .env. "
            "Vector search will fail until Qdrant is running."
        )
        return

    storage = _storage_dir()
    port = _http_port()
    env = os.environ.copy()
    env["QDRANT__SERVICE__HTTP_PORT"] = str(port)

    args = [binary, "--storage-path", str(storage)]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    try:
        _proc = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            cwd=str(_BACKEND_ROOT),
        )
        _started_by_us = True
    except Exception as e:
        logger.warning("Failed to start Qdrant subprocess: %s", e)
        _proc = None
        _started_by_us = False
        return

    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if _proc.poll() is not None:
            err = ""
            try:
                if _proc.stderr:
                    err = _proc.stderr.read().decode(errors="replace")[:800]
            except Exception:
                pass
            logger.error("Qdrant process exited during startup. stderr: %s", err or "(empty)")
            _proc = None
            _started_by_us = False
            return
        if _health_ok():
            logger.info("Started Qdrant (managed) at %s storage=%s", _base_url(), storage)
            return
        time.sleep(0.35)

    logger.warning(
        "Qdrant subprocess did not become ready within timeout; vector ops may fail until it listens on port %s.",
        port,
    )


def stop_qdrant_if_started() -> None:
    """Terminate Qdrant if this process started it."""
    global _proc, _started_by_us

    if not _started_by_us or _proc is None:
        return

    try:
        _proc.terminate()
        _proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            _proc.kill()
        except Exception:
            pass
    except Exception as e:
        logger.warning("Error stopping Qdrant subprocess: %s", e)
        try:
            _proc.kill()
        except Exception:
            pass
    finally:
        _proc = None
        _started_by_us = False
