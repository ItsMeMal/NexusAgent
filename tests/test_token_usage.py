import unittest
from unittest.mock import AsyncMock

from nexus.core.llm import LLMClient, normalize_token_usage


class TokenUsageNormalizationTests(unittest.TestCase):
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
            "_nexus_usage": {"prompt_tokens": 120, "completion_tokens": 35, "total_tokens": 155},
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


if __name__ == "__main__":
    unittest.main()
