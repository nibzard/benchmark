import os
import unittest

from pydantic import BaseModel

from browser_patches import (
    clear_anthropic_tool_use_retry_diagnostics,
    get_anthropic_tool_use_retry_diagnostics,
    install_anthropic_tool_use_retry,
)
from frameworks import serialize_usage
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage


class AgentOutput(BaseModel):
    value: str


class FakeUsage:
    def __init__(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_creation = None


class FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeToolBlock:
    type = "tool_use"

    def __init__(self, payload: dict) -> None:
        self.input = payload


class FakeResponse:
    def __init__(
        self,
        content: list,
        usage: FakeUsage,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason
        self.stop_details = None


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def create(self, **params):
        self.calls.append(params)
        if not self.responses:
            raise AssertionError("No fake response configured")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = FakeMessages(responses)


def make_llm(responses: list[FakeResponse]) -> tuple[ChatAnthropic, FakeClient]:
    client = FakeClient(responses)
    llm = ChatAnthropic(model="claude-opus-4-8", api_key="test-key")
    object.__setattr__(llm, "get_client", lambda: client)
    return llm, client


class AnthropicToolUseRetryPatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ.pop("ANTHROPIC_TOOL_USE_RETRY", None)
        os.environ.pop("ANTHROPIC_TOOL_USE_RETRY_LOG_TEXT", None)
        os.environ.pop("ANTHROPIC_TOOL_USE_RETRY_SAVE_TEXT", None)
        os.environ.pop("ANTHROPIC_TOOL_USE_RETRY_TEXT_LIMIT", None)
        install_anthropic_tool_use_retry()
        clear_anthropic_tool_use_retry_diagnostics()

    async def test_normal_tool_use_does_not_retry(self) -> None:
        llm, client = make_llm(
            [
                FakeResponse(
                    [FakeToolBlock({"value": "ok"})],
                    FakeUsage(input_tokens=11, output_tokens=3),
                )
            ]
        )

        result = await llm.ainvoke(
            [UserMessage(content="Return structured output")],
            output_format=AgentOutput,
        )

        self.assertEqual(result.completion.value, "ok")
        self.assertEqual(len(client.messages.calls), 1)
        self.assertEqual(get_anthropic_tool_use_retry_diagnostics(), [])

    async def test_missing_tool_use_retries_and_merges_usage(self) -> None:
        llm, client = make_llm(
            [
                FakeResponse(
                    [FakeTextBlock("I forgot the tool")],
                    FakeUsage(input_tokens=10, output_tokens=2),
                ),
                FakeResponse(
                    [FakeToolBlock({"value": "recovered"})],
                    FakeUsage(input_tokens=12, output_tokens=4),
                ),
            ]
        )

        result = await llm.ainvoke(
            [UserMessage(content="Return structured output")],
            output_format=AgentOutput,
        )

        self.assertEqual(result.completion.value, "recovered")
        self.assertEqual(len(client.messages.calls), 2)
        self.assertEqual(result.usage.prompt_tokens, 22)
        self.assertEqual(result.usage.completion_tokens, 6)
        serialized_usage = serialize_usage(result.usage)
        self.assertEqual(serialized_usage["total_prompt_tokens"], 22)
        self.assertEqual(serialized_usage["total_completion_tokens"], 6)
        self.assertEqual(serialized_usage["entry_count"], 1)

        diagnostics = get_anthropic_tool_use_retry_diagnostics()
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["event"], "anthropic_missing_tool_use")
        self.assertEqual(diagnostics[0]["phase"], "initial")
        self.assertEqual(diagnostics[0]["retry_outcome"], "recovered")
        self.assertNotIn("text_excerpt", diagnostics[0])

    async def test_missing_tool_use_can_capture_failed_text_when_enabled(self) -> None:
        os.environ["ANTHROPIC_TOOL_USE_RETRY_SAVE_TEXT"] = "true"
        os.environ["ANTHROPIC_TOOL_USE_RETRY_TEXT_LIMIT"] = "12"
        llm, _ = make_llm(
            [
                FakeResponse(
                    [FakeTextBlock("0123456789abcdef")],
                    FakeUsage(input_tokens=10, output_tokens=2),
                ),
                FakeResponse(
                    [FakeToolBlock({"value": "recovered"})],
                    FakeUsage(input_tokens=12, output_tokens=4),
                ),
            ]
        )

        await llm.ainvoke(
            [UserMessage(content="Return structured output")],
            output_format=AgentOutput,
        )

        diagnostics = get_anthropic_tool_use_retry_diagnostics()
        self.assertEqual(diagnostics[0]["failed_output_text"], "0123456789ab")
        self.assertEqual(diagnostics[0]["failed_output_text_limit"], 12)
        self.assertTrue(diagnostics[0]["failed_output_text_truncated"])

    async def test_retry_failure_preserves_diagnostics(self) -> None:
        llm, client = make_llm(
            [
                FakeResponse(
                    [FakeTextBlock("Still not a tool")],
                    FakeUsage(input_tokens=10, output_tokens=2),
                ),
                FakeResponse(
                    [FakeTextBlock("Still not a tool on retry")],
                    FakeUsage(input_tokens=12, output_tokens=4),
                ),
            ]
        )

        with self.assertRaises(ModelProviderError):
            await llm.ainvoke(
                [UserMessage(content="Return structured output")],
                output_format=AgentOutput,
            )

        self.assertEqual(len(client.messages.calls), 2)
        diagnostics = get_anthropic_tool_use_retry_diagnostics()
        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(diagnostics[0]["phase"], "initial")
        self.assertEqual(diagnostics[0]["retry_outcome"], "failed")
        self.assertEqual(diagnostics[1]["phase"], "retry")
        self.assertEqual(diagnostics[1]["retry_outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
