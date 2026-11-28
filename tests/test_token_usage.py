import unittest
from unittest.mock import AsyncMock, patch

from nolthira.core.llm import LLMClient, normalize_token_usage
from nolthira.providers.manager import parse_context_window_tokens, extract_model_context_window


class _FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeStreamContext:
    def __init__(self, lines):
        self.response = _FakeStreamResponse(lines)

    async def __aenter__(self):
        return await self.response.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        return await self.response.__aexit__(exc_type, exc, tb)


class _FakeAsyncClient:
    def __init__(self, lines):
        self.lines = lines
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers, json):
        self.payload = json
        return _FakeStreamContext(self.lines)


class TokenUsageNormalizationTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_openai_usage(self):
        self.assertEqual(
            normalize_token_usage({"prompt_tokens": 120, "completion_tokens": 35, "total_tokens": 155}),
            {"input_tokens": 120, "output_tokens": 35, "total_tokens": 155},
        )

    def test_normalizes_input_output_variants(self):
        self.assertEqual(
            normalize_token_usage({"input_tokens": 10, "output_tokens": 4}),
            {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        )

    def test_missing_usage_is_not_treated_as_provider_reported(self):
        self.assertIsNone(normalize_token_usage(None))
        self.assertIsNone(normalize_token_usage({}))

    async def test_client_records_provider_usage_and_session_totals(self):
        seen = []
        client = LLMClient(
            api_key="test",
            api_base="https://example.invalid/v1",
            model="test-model",
            context_window=32000,
            on_usage=seen.append,
        )
        client._standard_completion = AsyncMock(return_value={
            "role": "assistant",
            "content": "done",
            "_nolthira_usage": {"prompt_tokens": 120, "completion_tokens": 35, "total_tokens": 155},
        })
        result = await client.chat_completion(messages=[{"role": "user", "content": "hello"}])
        self.assertEqual(result["content"], "done")
        self.assertEqual(client.last_usage["source"], "api_reported")
        self.assertEqual(client.last_usage["total_tokens"], 155)
        self.assertEqual(client.last_usage["context_window"], 32000)
        self.assertEqual(client.session_usage["requests"], 1)
        self.assertEqual(seen[0]["input_tokens"], 120)

    async def test_client_labels_fallback_counts_as_estimated(self):
        client = LLMClient(
            api_key="test",
            api_base="https://example.invalid/v1",
            model="test-model",
        )
        client._standard_completion = AsyncMock(return_value={"role": "assistant", "content": "output"})
        await client.chat_completion(messages=[{"role": "user", "content": "input"}])
        self.assertEqual(client.last_usage["source"], "estimated")
        self.assertGreater(client.last_usage["total_tokens"], 0)
        self.assertEqual(client.session_usage["estimated_requests"], 1)

    async def test_streaming_requests_provider_usage_and_reads_final_usage_chunk(self):
        fake_client = _FakeAsyncClient([
            'data: {"choices":[{"delta":{"content":"hello"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":18,"completion_tokens":7,"total_tokens":25}}',
            "data: [DONE]",
        ])
        client = LLMClient(api_key="test", api_base="https://example.invalid/v1", model="test-model")
        emitted = []

        with patch("nolthira.core.llm.httpx.AsyncClient", return_value=fake_client):
            result = await client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                on_token=emitted.append,
            )

        self.assertEqual(result["content"], "hello")
        self.assertEqual(emitted, ["hello"])
        self.assertEqual(fake_client.payload["stream_options"], {"include_usage": True})
        self.assertEqual(client.last_usage["source"], "api_reported")
        self.assertEqual(client.last_usage["input_tokens"], 18)
        self.assertEqual(client.last_usage["output_tokens"], 7)
        self.assertEqual(client.last_usage["total_tokens"], 25)

    def test_parses_explicit_context_window_sizes(self):
        self.assertEqual(parse_context_window_tokens(131072), 131072)
        self.assertEqual(parse_context_window_tokens("128k"), 128000)
        self.assertEqual(parse_context_window_tokens("1.5M"), 1500000)
        self.assertEqual(parse_context_window_tokens("Auto"), 0)
        self.assertEqual(parse_context_window_tokens(None), 0)

    def test_extracts_context_only_for_exact_model_and_real_context_fields(self):
        payload = {
            "data": [
                {"id": "other-model", "context_length": 64000},
                {"id": "my-model", "capabilities": {"contextWindow": "256k"}, "max_tokens": 4096},
            ]
        }
        self.assertEqual(extract_model_context_window(payload, "my-model"), 256000)
        self.assertEqual(extract_model_context_window(payload, "missing-model"), 0)
        self.assertEqual(extract_model_context_window({"data": [{"id": "my-model", "max_tokens": 8192}]}, "my-model"), 0)


if __name__ == "__main__":
    unittest.main()
