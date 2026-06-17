"""Steel -- https://steel.dev

Residential proxy and captcha solving.
Requires: STEEL_API_KEY env var.

Note: Steel's WebSocket host does not support IPv6. The monkey-patch below
forces IPv4 resolution for connect.steel.dev to avoid 502 errors.
"""

import os
import socket
from contextvars import ContextVar

import httpx

from browsers import retry_on_429

_session_id: ContextVar[str | None] = ContextVar("steel_session_id", default=None)

_original_getaddrinfo = socket.getaddrinfo
STEALTH_CAPABLE = True
REMOTE_TYPING_FALLBACK = True


def _getaddrinfo_ipv4_for_steel(host, port, family=0, *args, **kwargs):
    if host == "connect.steel.dev" and family == 0:
        family = socket.AF_INET
    return _original_getaddrinfo(host, port, family, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo_ipv4_for_steel


def stealth_enabled() -> bool:
    return os.environ.get("STEEL_USE_STEALTH", "").lower() in ("1", "true", "yes")


def current_session_id() -> str | None:
    return _session_id.get()


async def connect() -> str:
    api_key = os.environ["STEEL_API_KEY"]
    # Keep the provider session slightly longer than the benchmark's 1800s
    # task timeout so the runner, not Steel, owns task termination semantics.
    payload = {"useProxy": True, "solveCaptcha": True, "timeout": 1860000}
    if stealth_enabled():
        payload["experimentalFeatures"] = ["useStealthBrowser"]

    async def _create():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.steel.dev/v1/sessions",
                headers={"steel-api-key": api_key},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    data = await retry_on_429(_create)
    _session_id.set(data.get("id"))
    return f"{data['websocketUrl']}&apiKey={api_key}"


async def disconnect() -> None:
    session_id = _session_id.get()
    if not session_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"https://api.steel.dev/v1/sessions/{session_id}",
                headers={"steel-api-key": os.environ["STEEL_API_KEY"]},
                timeout=30,
            )
    finally:
        _session_id.set(None)
