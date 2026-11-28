import unittest

from nolthira.providers.manager import PROVIDERS, ProviderManager


class ProviderCatalogTests(unittest.TestCase):
    EXPECTED_PROVIDERS = {
        "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
        "sambanova": ("https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY"),
        "deepinfra": ("https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
        "siliconflow": ("https://api.siliconflow.com/v1", "SILICONFLOW_API_KEY"),
        "novita": ("https://api.novita.ai/v3/openai", "NOVITA_API_KEY"),
        "nebius": ("https://api.tokenfactory.nebius.com/v1", "NEBIUS_API_KEY"),
        "hyperbolic": ("https://api.hyperbolic.ai/inference/v1", "HYPERBOLIC_API_KEY"),
        "nvidia_nim": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
        "alibaba_model_studio": (
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "DASHSCOPE_API_KEY",
        ),
        "zai": ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
        "minimax": ("https://api.minimax.io/v1", "MINIMAX_API_KEY"),
        "byteplus": ("https://ark.ap-southeast.bytepluses.com/api/v3", "ARK_API_KEY"),
        "huggingface": ("https://router.huggingface.co/v1", "HF_TOKEN"),
        "bedrock": (
            "https://bedrock-mantle.us-east-1.api.aws/v1",
            "AWS_BEDROCK_API_KEY",
        ),
    }

    DETECTION_URLS = {
        "cerebras": "https://api.cerebras.ai/v1",
        "sambanova": "https://api.sambanova.ai/v1",
        "deepinfra": "https://api.deepinfra.com/v1/openai",
        "siliconflow": "https://api.siliconflow.com/v1",
        "novita": "https://api.novita.ai/v3/openai",
        "nebius": "https://api.tokenfactory.nebius.com/v1",
        "hyperbolic": "https://api.hyperbolic.ai/inference/v1",
        "nvidia_nim": "https://integrate.api.nvidia.com/v1",
        "moonshot": "https://api.moonshot.ai/v1",
        "alibaba_model_studio": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "zai": "https://api.z.ai/api/paas/v4",
        "minimax": "https://api.minimax.io/v1",
        "byteplus": "https://ark.ap-southeast.bytepluses.com/api/v3",
        "huggingface": "https://router.huggingface.co/v1",
        "bedrock": "https://bedrock-mantle.eu-west-1.api.aws/v1",
    }

    def test_new_profiles_are_registered_with_expected_credentials_and_protocol(self):
        for provider_id, (base_url, env_key) in self.EXPECTED_PROVIDERS.items():
            with self.subTest(provider=provider_id):
                profile = PROVIDERS[provider_id]
                self.assertEqual(profile.default_base, base_url)
                self.assertEqual(profile.env_key, env_key)
                self.assertEqual(profile.protocol, "openai-chat-completions")
                self.assertFalse(profile.is_local)

    def test_provider_detection_for_all_new_profiles(self):
        for provider_id, api_base in self.DETECTION_URLS.items():
            with self.subTest(provider=provider_id):
                self.assertEqual(
                    ProviderManager.detect_active_provider(api_base).id,
                    provider_id,
                )

    def test_legacy_profiles_remain_available(self):
        for provider_id in (
            "openrouter",
            "openai",
            "gemini",
            "anthropic",
            "deepseek",
            "groq",
            "mistral",
            "together",
            "xai",
            "fireworks",
            "perplexity",
            "cohere",
            "nous",
            "ollama",
            "vllm",
            "custom",
        ):
            with self.subTest(provider=provider_id):
                self.assertIn(provider_id, PROVIDERS)

    def test_legacy_profiles_are_not_mislabeled_as_verified_openai_protocol(self):
        # Some legacy entries point at native APIs that the current LLMClient does
        # not yet adapt (for example Anthropic Messages and Cohere v2).
        self.assertEqual(PROVIDERS["anthropic"].protocol, "unverified")
        self.assertEqual(PROVIDERS["cohere"].protocol, "unverified")

    def test_mallss_route_profile_uses_owned_gateway_and_oauth_login(self):
        profile = PROVIDERS["mallss_nexus_route"]
        self.assertEqual(profile.default_base, "https://ai-router.mallss-nexus.sbs/v1")
        self.assertEqual(profile.env_key, "")
        self.assertEqual(profile.protocol, "openai-chat-completions")
        self.assertEqual(
            ProviderManager.detect_active_provider("https://ai-router.mallss-nexus.sbs/v1").id,
            "mallss_nexus_route",
        )

    def test_provider_list_contains_all_legacy_and_new_profiles(self):
        self.assertEqual(len(ProviderManager.list_providers()), 32)


if __name__ == "__main__":
    unittest.main()
