import unittest
from nexus.core.llm import normalize_token_usage


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


if __name__ == "__main__":
    unittest.main()
