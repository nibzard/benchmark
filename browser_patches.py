"""Runtime browser-use patches for remote browser benchmark providers."""

import asyncio
import hashlib
import logging
import os
from typing import Any


_REMOTE_TYPE_PATCH_INSTALLED = False
_ANTHROPIC_TOOL_USE_PATCH_INSTALLED = False
_ANTHROPIC_TOOL_USE_DIAGNOSTICS: list[dict[str, Any]] = []

_NO_TOOL_USE_ERROR = "Expected tool use in response but none found"
_FALSE_VALUES = {"0", "false", "no", "off"}

logger = logging.getLogger(__name__)


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSE_VALUES


def _get_mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _serialize_usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    if hasattr(usage, "dict"):
        return usage.dict()
    if isinstance(usage, dict):
        return usage
    return {
        key: getattr(usage, key)
        for key in (
            "prompt_tokens",
            "prompt_cached_tokens",
            "prompt_cache_creation_tokens",
            "prompt_cache_creation_5m_tokens",
            "prompt_cache_creation_1h_tokens",
            "prompt_image_tokens",
            "completion_tokens",
            "total_tokens",
            "pricing_multiplier",
        )
        if hasattr(usage, key)
    }


def get_anthropic_tool_use_retry_diagnostics(reset: bool = False) -> list[dict[str, Any]]:
    """Return safe diagnostics captured by the Anthropic no-tool-use patch."""

    diagnostics = [dict(item) for item in _ANTHROPIC_TOOL_USE_DIAGNOSTICS]
    if reset:
        _ANTHROPIC_TOOL_USE_DIAGNOSTICS.clear()
    return diagnostics


def clear_anthropic_tool_use_retry_diagnostics() -> None:
    _ANTHROPIC_TOOL_USE_DIAGNOSTICS.clear()


def _content_block_diagnostics(response: Any) -> dict[str, Any]:
    block_types: list[str] = []
    text_parts: list[str] = []

    for block in getattr(response, "content", []) or []:
        block_type = str(getattr(block, "type", type(block).__name__))
        block_types.append(block_type)
        if block_type == "text":
            text = getattr(block, "text", None)
            if text:
                text_parts.append(str(text))

    text = "\n".join(text_parts)
    diagnostics: dict[str, Any] = {
        "content_block_types": block_types,
        "text_char_count": len(text),
    }
    if text:
        diagnostics["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if _env_enabled("ANTHROPIC_TOOL_USE_RETRY_LOG_TEXT", False):
            diagnostics["text_excerpt"] = text[:500]

    return diagnostics


def _sum_optional_int(left: Any, right: Any) -> int | None:
    if left is None and right is None:
        return None
    return int(left or 0) + int(right or 0)


def _merge_invocation_usage(first: Any, second: Any) -> Any:
    if first is None:
        return second
    if second is None:
        return first

    from browser_use.llm.views import ChatInvokeUsage

    pricing_multiplier = getattr(second, "pricing_multiplier", None)
    if pricing_multiplier is None:
        pricing_multiplier = getattr(first, "pricing_multiplier", None)

    return ChatInvokeUsage(
        prompt_tokens=int(getattr(first, "prompt_tokens", 0) or 0)
        + int(getattr(second, "prompt_tokens", 0) or 0),
        prompt_cached_tokens=_sum_optional_int(
            getattr(first, "prompt_cached_tokens", None),
            getattr(second, "prompt_cached_tokens", None),
        ),
        prompt_cache_creation_tokens=_sum_optional_int(
            getattr(first, "prompt_cache_creation_tokens", None),
            getattr(second, "prompt_cache_creation_tokens", None),
        ),
        prompt_cache_creation_5m_tokens=_sum_optional_int(
            getattr(first, "prompt_cache_creation_5m_tokens", None),
            getattr(second, "prompt_cache_creation_5m_tokens", None),
        ),
        prompt_cache_creation_1h_tokens=_sum_optional_int(
            getattr(first, "prompt_cache_creation_1h_tokens", None),
            getattr(second, "prompt_cache_creation_1h_tokens", None),
        ),
        prompt_image_tokens=_sum_optional_int(
            getattr(first, "prompt_image_tokens", None),
            getattr(second, "prompt_image_tokens", None),
        ),
        completion_tokens=int(getattr(first, "completion_tokens", 0) or 0)
        + int(getattr(second, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(first, "total_tokens", 0) or 0)
        + int(getattr(second, "total_tokens", 0) or 0),
        pricing_multiplier=pricing_multiplier,
    )


def _is_forced_tool_request(params: dict[str, Any]) -> bool:
    tool_choice = params.get("tool_choice")
    return bool(params.get("tools")) and _get_mapping_value(tool_choice, "type") == "tool"


def _pending_no_tool_records(llm: Any) -> list[dict[str, Any]]:
    pending = getattr(llm, "_anthropic_no_tool_pending", None)
    if pending is None:
        pending = []
        object.__setattr__(llm, "_anthropic_no_tool_pending", pending)
    return pending


def _trim_pending_no_tool_records(llm: Any, size: int) -> None:
    pending = _pending_no_tool_records(llm)
    del pending[size:]


def install_anthropic_tool_use_retry() -> None:
    """Retry Anthropic structured-output calls once if a forced tool call is missing.

    browser-use expects Anthropic to return the forced AgentOutput tool call.
    Some long-running benchmark steps intermittently return text without a
    tool_use block. This patch captures safe response metadata, retries once
    with a narrow clarification, and carries first-call usage into the returned
    usage object so benchmark token totals include the failed paid response.
    """

    global _ANTHROPIC_TOOL_USE_PATCH_INSTALLED
    if _ANTHROPIC_TOOL_USE_PATCH_INSTALLED:
        return

    from browser_use.llm.anthropic.chat import ChatAnthropic
    from browser_use.llm.exceptions import ModelProviderError
    from browser_use.llm.messages import UserMessage

    original_ainvoke = ChatAnthropic.ainvoke
    original_create_message = ChatAnthropic._create_message

    async def patched_create_message(self: Any, **params: Any) -> Any:
        response = await original_create_message(self, **params)
        if not _is_forced_tool_request(params):
            return response
        if not self._is_message_like_response(response):
            return response

        has_tool_use = any(
            getattr(block, "type", None) == "tool_use"
            for block in getattr(response, "content", []) or []
        )
        if has_tool_use:
            return response

        try:
            usage = self._get_usage(response)
            usage_data = _serialize_usage(usage)
        except Exception:
            usage = None
            usage_data = None

        diagnostic: dict[str, Any] = {
            "event": "anthropic_missing_tool_use",
            "phase": "retry" if getattr(self, "_anthropic_tool_retry_active", False) else "initial",
            "model": str(getattr(self, "model", "")),
            "tool_name": _get_mapping_value(params.get("tool_choice"), "name"),
            "stop_reason": getattr(response, "stop_reason", None),
            "stop_details": self._get_stop_details(response),
            "usage": usage_data,
            "retry_attempted": False,
            **_content_block_diagnostics(response),
        }
        _ANTHROPIC_TOOL_USE_DIAGNOSTICS.append(diagnostic)
        _pending_no_tool_records(self).append(
            {"diagnostic": diagnostic, "usage": usage}
        )
        return response

    async def patched_ainvoke(
        self: Any, messages: list[Any], output_format: type[Any] | None = None, **kwargs: Any
    ) -> Any:
        if output_format is None or not _env_enabled("ANTHROPIC_TOOL_USE_RETRY", True):
            return await original_ainvoke(self, messages, output_format, **kwargs)

        pending_start = len(_pending_no_tool_records(self))
        try:
            return await original_ainvoke(self, messages, output_format, **kwargs)
        except ModelProviderError as exc:
            if _NO_TOOL_USE_ERROR not in str(exc):
                raise

            records = _pending_no_tool_records(self)
            initial_record = records[-1] if len(records) > pending_start else None
            diagnostic = initial_record["diagnostic"] if initial_record else None
            if diagnostic is not None:
                diagnostic["retry_attempted"] = True

            logger.warning(
                "Anthropic response omitted required tool_use for %s; retrying once.",
                getattr(output_format, "__name__", "structured output"),
            )
            retry_messages = list(messages) + [
                UserMessage(
                    content=(
                        "The previous response omitted the required structured tool call. "
                        f"Retry now using the {getattr(output_format, '__name__', 'AgentOutput')} "
                        "tool exactly once, with valid arguments matching its schema."
                    )
                )
            ]

            object.__setattr__(self, "_anthropic_tool_retry_active", True)
            try:
                result = await original_ainvoke(
                    self, retry_messages, output_format, **kwargs
                )
            except Exception as retry_exc:
                if diagnostic is not None:
                    diagnostic["retry_outcome"] = "failed"
                    diagnostic["retry_error_type"] = type(retry_exc).__name__
                    diagnostic["retry_error"] = str(retry_exc)[:500]
                for retry_record in _pending_no_tool_records(self)[pending_start + 1 :]:
                    retry_record["diagnostic"]["retry_outcome"] = "failed"
                raise
            finally:
                object.__setattr__(self, "_anthropic_tool_retry_active", False)
                _trim_pending_no_tool_records(self, pending_start)

            failed_usage = initial_record["usage"] if initial_record else None
            if failed_usage is not None:
                result.usage = _merge_invocation_usage(failed_usage, result.usage)
            if diagnostic is not None:
                diagnostic["retry_outcome"] = "recovered"
                diagnostic["merged_usage"] = _serialize_usage(result.usage)
            return result

    ChatAnthropic._create_message = patched_create_message
    ChatAnthropic.ainvoke = patched_ainvoke
    _ANTHROPIC_TOOL_USE_PATCH_INSTALLED = True


def install_remote_typing_fallback(timeout: float = 20.0) -> None:
    """Bound browser-use typing and fall back to direct DOM assignment.

    browser-use types text through many low-level CDP key events. On remote CDP
    providers a single key event can hang long enough to stall the agent. This
    patch keeps browser-use's normal typing path first, but gives it a bounded
    window before setting the target element value directly and dispatching the
    DOM events frameworks expect.
    """

    global _REMOTE_TYPE_PATCH_INSTALLED
    if _REMOTE_TYPE_PATCH_INSTALLED:
        return

    from browser_use.browser.watchdogs.default_action_watchdog import (
        DefaultActionWatchdog,
    )

    original_on_type = DefaultActionWatchdog.on_TypeTextEvent

    async def _set_text_directly(self: Any, event: Any) -> dict | None:
        element_node = event.node
        backend_node_id = element_node.backend_node_id
        if not backend_node_id:
            await self._type_to_page(event.text)
            return None

        cdp_session = await self.browser_session.cdp_client_for_node(element_node)
        result = await self.browser_session.cdp_client.send.DOM.resolveNode(
            params={"backendNodeId": backend_node_id},
            session_id=cdp_session.session_id,
        )
        object_id = result["object"]["objectId"]

        value_script = """
            function(newValue, shouldClear) {
                const element = this;
                if (!element) {
                    return { ok: false, error: 'No element was resolved' };
                }

                function describe(target) {
                    const tag = target.tagName ? target.tagName.toLowerCase() : 'unknown';
                    const id = target.id ? `#${target.id}` : '';
                    const name = target.getAttribute && target.getAttribute('name')
                        ? `[name="${target.getAttribute('name')}"]`
                        : '';
                    return `${tag}${id}${name}`;
                }

                function dispatchTextEvents(target, insertedText, inputType) {
                    try {
                        target.dispatchEvent(new InputEvent('input', {
                            bubbles: true,
                            cancelable: true,
                            data: insertedText,
                            inputType
                        }));
                    } catch (_) {
                        target.dispatchEvent(new Event('input', {
                            bubbles: true,
                            cancelable: true
                        }));
                    }
                    target.dispatchEvent(new Event('change', {
                        bubbles: true,
                        cancelable: true
                    }));
                }

                function setNativeValue(target, value) {
                    const proto = target instanceof HTMLTextAreaElement
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (desc && desc.set) {
                        desc.set.call(target, value);
                    } else {
                        target.value = value;
                    }
                }

                element.focus();
                const inputType = shouldClear ? 'insertReplacementText' : 'insertText';

                if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
                    const nextValue = shouldClear ? newValue : `${element.value || ''}${newValue}`;
                    setNativeValue(element, nextValue);
                    dispatchTextEvents(element, newValue, inputType);
                    return {
                        ok: true,
                        target: describe(element),
                        value: nextValue,
                        valueLength: nextValue.length
                    };
                }

                if (element instanceof HTMLElement && element.isContentEditable) {
                    if (shouldClear) {
                        element.textContent = '';
                    }
                    element.append(document.createTextNode(newValue));
                    dispatchTextEvents(element, newValue, inputType);
                    const nextValue = element.textContent || '';
                    return {
                        ok: true,
                        target: describe(element),
                        value: nextValue,
                        valueLength: nextValue.length
                    };
                }

                return {
                    ok: false,
                    target: describe(element),
                    error: `Element is not text-editable: ${describe(element)}`
                };
            }
        """
        set_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
            params={
                "objectId": object_id,
                "functionDeclaration": value_script,
                "arguments": [
                    {"value": event.text},
                    {"value": bool(event.clear or not event.text)},
                ],
                "returnByValue": True,
            },
            session_id=cdp_session.session_id,
        )

        value_result = set_result.get("result", {}).get("value") or {}
        if not value_result.get("ok"):
            raise RuntimeError(
                value_result.get("error") or "Direct DOM typing fallback failed"
            )

        metadata: dict[str, Any] = {
            "typing_fallback": "direct_dom",
            "target": value_result.get("target"),
            "value_length": value_result.get("valueLength"),
        }
        if not event.is_sensitive:
            metadata["actual_value"] = value_result.get("value")
        return metadata

    async def patched_on_type(self: Any, event: Any) -> dict | None:
        try:
            return await asyncio.wait_for(original_on_type(self, event), timeout=timeout)
        except asyncio.TimeoutError:
            node = event.node
            index_for_logging = node.backend_node_id or "unknown"
            self.logger.warning(
                "TypeTextEvent exceeded %.1fs for element %s; using direct DOM fallback.",
                timeout,
                index_for_logging,
            )
            return await _set_text_directly(self, event)

    patched_on_type.__name__ = "on_TypeTextEvent"
    DefaultActionWatchdog.on_TypeTextEvent = patched_on_type
    _REMOTE_TYPE_PATCH_INSTALLED = True
