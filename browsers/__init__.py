"""Browser provider registry."""

import importlib

from browsers.util import retry_on_429
from browsers import (
    anchor,
    browser_use_cloud,
    browserbase,
    browserless,
    driver,
    hyperbrowser,
    local_headful,
    local_headless,
    onkernel,
    rebrowser,
    steel,
)

PROVIDERS = [
    "anchor",
    "browserbase",
    "browserless",
    "driver",
    "hyperbrowser",
    "local_headful",
    "local_headless",
    "onkernel",
    "rebrowser",
    "steel",
]

BROWSERS = {
    "anchor": anchor,
    "browser-use-cloud": browser_use_cloud,
    "browserbase": browserbase,
    "browserless": browserless,
    "driver": driver,
    "hyperbrowser": hyperbrowser,
    "local_headful": local_headful,
    "local_headless": local_headless,
    "onkernel": onkernel,
    "rebrowser": rebrowser,
    "steel": steel,
}


def get_provider(name: str):
    """Import and return a browser provider module by name."""
    if name not in PROVIDERS:
        raise ValueError(f"Unknown browser provider: {name}. Available: {PROVIDERS}")
    return importlib.import_module(f"browsers.{name}")


def provider_arm_config(name: str) -> dict:
    """Best-effort snapshot of a provider's arm-defining config, or ``{}``.

    A provider opts in by defining a module-level ``arm_config()`` (e.g. Steel's
    solver/stealth/region/proxy knobs). This never raises: arm labeling is run
    metadata, not something that should be allowed to fail a run.
    """
    try:
        provider = get_provider(name)
    except Exception:
        return {}
    fn = getattr(provider, "arm_config", None)
    if not callable(fn):
        return {}
    try:
        cfg = fn()
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}
