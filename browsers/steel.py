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


def solve_captcha_enabled() -> bool:
    # Defaults to True (Steel's captcha solver on). Set STEEL_SOLVE_CAPTCHA=false
    # to disable, e.g. for benchmarking agent behavior against unsolved captchas.
    return os.environ.get("STEEL_SOLVE_CAPTCHA", "true").lower() in ("1", "true", "yes")


def proxy_config() -> bool | dict:
    country = os.environ.get("STEEL_PROXY_COUNTRY")
    state = os.environ.get("STEEL_PROXY_STATE")
    city = os.environ.get("STEEL_PROXY_CITY")
    if not any((country, state, city)):
        return True

    geolocation = {}
    if country:
        geolocation["country"] = country
    if state:
        geolocation["state"] = state
    if city:
        geolocation["city"] = city
    return {"geolocation": geolocation}


def current_session_id() -> str | None:
    return _session_id.get()


async def connect() -> str:
    api_key = os.environ["STEEL_API_KEY"]
    # Keep the provider session slightly longer than the benchmark's 1800s
    # task timeout so the runner, not Steel, owns task termination semantics.
    payload = {
        "useProxy": proxy_config(),
        "solveCaptcha": solve_captcha_enabled(),
        "timeout": 1860000,
    }
    if region := os.environ.get("STEEL_REGION"):
        payload["region"] = region
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
