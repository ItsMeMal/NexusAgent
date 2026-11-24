import os
import re
import httpx
from urllib.parse import urlparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from ..config import config

@dataclass
class ModelInfo:
    id: str
    name: str
    tag: str = "Standard"
    context: str = "128k"
    description: str = ""

@dataclass
class ProviderProfile:
    id: str
    name: str
    default_base: str
    env_key: str
    description: str
    is_local: bool = False
    curated_models: List[ModelInfo] = field(default_factory=list)

PROVIDERS: Dict[str, ProviderProfile] = {
    "openrouter": ProviderProfile(
        id="openrouter",
        name="OpenRouter (Universal Gateway)",
        default_base="https://openrouter.ai/api/v1",
        env_key="OPENROUTER_API_KEY",
        description="Unified router for Claude, GPT-4o, DeepSeek, and 200+ models",
        curated_models=[
            ModelInfo(id="deepseek/deepseek-r1", name="DeepSeek R1", tag="Reasoning", context="128k"),
            ModelInfo(id="deepseek/deepseek-chat", name="DeepSeek V3", tag="Popular", context="64k"),
            ModelInfo(id="anthropic/claude-3.5-sonnet", name="Claude 3.5 Sonnet", tag="Coding Leader", context="200k"),
            ModelInfo(id="openai/gpt-4o", name="GPT-4o", tag="Flagship", context="128k"),
            ModelInfo(id="meta-llama/llama-3.3-70b-instruct", name="Llama 3.3 70B", tag="Open Weights", context="128k"),
        ]
    ),
    "openai": ProviderProfile(
        id="openai",
        name="OpenAI Official",
        default_base="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        description="Official OpenAI API",
        curated_models=[
            ModelInfo(id="gpt-4o", name="GPT-4o", tag="Flagship", context="128k"),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", tag="Fast", context="128k"),
            ModelInfo(id="o1", name="o1 Reasoning", tag="Reasoning", context="200k"),
            ModelInfo(id="o3-mini", name="o3 Mini", tag="Reasoning", context="200k"),
        ]
    ),
    "gemini": ProviderProfile(
        id="gemini",
        name="Google Gemini",
        default_base="https://generativelanguage.googleapis.com/v1beta/openai",
        env_key="GEMINI_API_KEY",
        description="Google Gemini 2.0 / 1.5 Pro via OpenAI compatibility",
        curated_models=[
            ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", tag="Ultra Fast", context="1M"),
            ModelInfo(id="gemini-1.5-pro", name="Gemini 1.5 Pro", tag="Deep Analysis", context="2M"),
            ModelInfo(id="gemini-1.5-flash", name="Gemini 1.5 Flash", tag="Fast", context="1M"),
        ]
    ),
    "anthropic": ProviderProfile(
        id="anthropic",
        name="Anthropic Claude (Gateway/Proxy)",
        default_base="https://api.anthropic.com/v1",
        env_key="ANTHROPIC_API_KEY",
        description="Anthropic Claude official API or compatible proxy",
        curated_models=[
            ModelInfo(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", tag="Top Coding", context="200k"),
            ModelInfo(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", tag="Fast Coding", context="200k"),
            ModelInfo(id="claude-3-opus-20240229", name="Claude 3 Opus", tag="Complex Reasoning", context="200k"),
        ]
    ),
    "deepseek": ProviderProfile(
        id="deepseek",
        name="DeepSeek Official",
        default_base="https://api.deepseek.com/v1",
        env_key="DEEPSEEK_API_KEY",
        description="Official DeepSeek API endpoint",
        curated_models=[
            ModelInfo(id="deepseek-chat", name="DeepSeek-V3", tag="General", context="64k"),
            ModelInfo(id="deepseek-reasoner", name="DeepSeek-R1", tag="Reasoning", context="64k"),
        ]
    ),
    "groq": ProviderProfile(
        id="groq",
        name="Groq (LPU Ultra-Fast)",
        default_base="https://api.groq.com/openai/v1",
        env_key="GROQ_API_KEY",
        description="Ultra-fast LPU inference (500+ tokens/sec)",
        curated_models=[
            ModelInfo(id="llama-3.3-70b-versatile", name="Llama 3.3 70B", tag="Fast Flagship", context="128k"),
            ModelInfo(id="llama-3.1-8b-instant", name="Llama 3.1 8B", tag="Speed King", context="128k"),
            ModelInfo(id="deepseek-r1-distill-llama-70b", name="DeepSeek R1 70B", tag="Reasoning", context="128k"),
            ModelInfo(id="mixtral-8x7b-32768", name="Mixtral 8x7B", tag="Balanced", context="32k"),
        ]
    ),
    "mistral": ProviderProfile(
        id="mistral",
        name="Mistral AI Official",
        default_base="https://api.mistral.ai/v1",
        env_key="MISTRAL_API_KEY",
        description="Official Mistral & Codestral API",
        curated_models=[
            ModelInfo(id="codestral-latest", name="Codestral", tag="Coding", context="256k"),
            ModelInfo(id="mistral-large-latest", name="Mistral Large", tag="Flagship", context="128k"),
            ModelInfo(id="pixtral-large-latest", name="Pixtral Large", tag="Vision", context="128k"),
        ]
    ),
    "together": ProviderProfile(
        id="together",
        name="Together AI",
        default_base="https://api.together.xyz/v1",
        env_key="TOGETHER_API_KEY",
        description="Together AI open-source cloud inference",
        curated_models=[
            ModelInfo(id="meta-llama/Llama-3.3-70B-Instruct-Turbo", name="Llama 3.3 70B Turbo", tag="Fast", context="128k"),
            ModelInfo(id="deepseek-ai/DeepSeek-R1", name="DeepSeek R1", tag="Reasoning", context="128k"),
            ModelInfo(id="Qwen/Qwen2.5-Coder-32B-Instruct", name="Qwen 2.5 Coder 32B", tag="Coding", context="32k"),
        ]
    ),
    "xai": ProviderProfile(
        id="xai",
        name="xAI (Grok)",
        default_base="https://api.x.ai/v1",
        env_key="XAI_API_KEY",
        description="Official xAI Grok inference endpoint",
        curated_models=[
            ModelInfo(id="grok-2-latest", name="Grok 2", tag="Flagship", context="128k"),
            ModelInfo(id="grok-beta", name="Grok Beta", tag="Fast", context="128k"),
        ]
    ),
    "fireworks": ProviderProfile(
        id="fireworks",
        name="Fireworks AI",
        default_base="https://api.fireworks.ai/inference/v1",
        env_key="FIREWORKS_API_KEY",
        description="High-speed serverless model deployment",
        curated_models=[
            ModelInfo(id="accounts/fireworks/models/llama-v3p3-70b-instruct", name="Llama 3.3 70B", tag="Fast", context="128k"),
            ModelInfo(id="accounts/fireworks/models/deepseek-r1", name="DeepSeek R1", tag="Reasoning", context="128k"),
        ]
    ),
    "perplexity": ProviderProfile(
        id="perplexity",
        name="Perplexity AI",
        default_base="https://api.perplexity.ai",
        env_key="PERPLEXITY_API_KEY",
        description="Perplexity AI search & reasoning models",
        curated_models=[
            ModelInfo(id="sonar-pro", name="Sonar Pro", tag="Live Search", context="128k"),
            ModelInfo(id="sonar", name="Sonar", tag="Search", context="128k"),
            ModelInfo(id="sonar-reasoning", name="Sonar Reasoning", tag="Reasoning", context="128k"),
        ]
    ),
    "cohere": ProviderProfile(
        id="cohere",
        name="Cohere",
        default_base="https://api.cohere.com/v2",
        env_key="COHERE_API_KEY",
        description="Cohere Command R & Command R+ models",
        curated_models=[
            ModelInfo(id="command-r-plus-08-2024", name="Command R+", tag="RAG/Tools", context="128k"),
            ModelInfo(id="command-r-08-2024", name="Command R", tag="Fast", context="128k"),
        ]
    ),
    "nous": ProviderProfile(
        id="nous",
        name="Nous Portal",
        default_base="https://inference.nousresearch.com/v1",
        env_key="NOUS_API_KEY",
        description="High-throughput inference API",
        curated_models=[
            ModelInfo(id="deepseek-ai/deepseek-r1", name="DeepSeek R1", tag="Flagship", context="128k"),
            ModelInfo(id="meta-llama/llama-3.1-70b", name="Llama 3.1 70B", tag="Balanced", context="128k"),
        ]
    ),
    "ollama": ProviderProfile(
        id="ollama",
        name="Ollama (Local / Offline)",
        default_base="http://localhost:11434/v1",
        env_key="",
        description="Local offline models running on your machine (Ollama)",
        is_local=True
    ),
    "vllm": ProviderProfile(
        id="vllm",
        name="vLLM / LM Studio (Local)",
        default_base="http://localhost:1234/v1",
        env_key="",
        description="Local inference server via vLLM, LM Studio, or llama.cpp",
        is_local=True
    ),
    "custom": ProviderProfile(
        id="custom",
        name="Custom Router (OneAPI / LiteLLM / Self-Hosted)",
        default_base="",
        env_key="OPENAI_API_KEY",
        description="Custom OpenAI-compatible router, aggregator, or reverse proxy"
    )
}

def _format_context_size(raw_val: Any) -> str:
    try:
        val = int(raw_val)
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M".replace(".0M", "M")
        elif val >= 1_000:
            return f"{val // 1_000}k"
        return str(val)
    except Exception:
        return str(raw_val) if raw_val else "Auto"

def _detect_tags(model_id: str, raw_meta: Dict[str, Any]) -> str:
    mid = model_id.lower()
    tags = []
    
    if "free" in mid:
        tags.append("Free")
    if any(k in mid for k in ("r1", "o1", "o3", "reasoner", "reasoning")):
        tags.append("Reasoning")
    elif "claude" in mid:
        tags.append("Claude")
    elif "gemini" in mid:
        tags.append("Gemini")
    elif "gpt" in mid:
        tags.append("GPT")
    elif "grok" in mid:
        tags.append("Grok")
    elif "deepseek" in mid:
        tags.append("DeepSeek")
    elif "hermes" in mid:
        tags.append("Instruct")
    elif "code" in mid or "codex" in mid:
        tags.append("Coding")

    caps = raw_meta.get("capabilities", {})
    if isinstance(caps, dict):
        if caps.get("vision") and "Vision" not in tags:
            tags.append("Vision")
        if caps.get("tools") and "Tools" not in tags:
            tags.append("Tools")

    if not tags:
        tags.append("General")

    return "/".join(tags[:2])

class ProviderManager:
    @staticmethod
    def list_providers() -> List[ProviderProfile]:
        return list(PROVIDERS.values())

    @staticmethod
    def get_provider(provider_id: str) -> Optional[ProviderProfile]:
        return PROVIDERS.get(provider_id.lower())

    @staticmethod
    def detect_active_provider(api_base: str) -> ProviderProfile:
        base_lower = api_base.lower()
        if "openrouter.ai" in base_lower:
            return PROVIDERS["openrouter"]
        elif "api.openai.com" in base_lower:
            return PROVIDERS["openai"]
        elif "googleapis.com" in base_lower:
            return PROVIDERS["gemini"]
        elif "anthropic.com" in base_lower:
            return PROVIDERS["anthropic"]
        elif "deepseek.com" in base_lower:
            return PROVIDERS["deepseek"]
        elif "groq.com" in base_lower:
            return PROVIDERS["groq"]
        elif "mistral.ai" in base_lower:
            return PROVIDERS["mistral"]
        elif "together.xyz" in base_lower or "together.ai" in base_lower:
            return PROVIDERS["together"]
        elif "x.ai" in base_lower:
            return PROVIDERS["xai"]
        elif "fireworks.ai" in base_lower:
            return PROVIDERS["fireworks"]
        elif "perplexity.ai" in base_lower:
            return PROVIDERS["perplexity"]
        elif "cohere.com" in base_lower or "cohere.ai" in base_lower:
            return PROVIDERS["cohere"]
        elif "nousresearch" in base_lower:
            return PROVIDERS["nous"]
        elif "localhost:11434" in base_lower or "127.0.0.1:11434" in base_lower:
            return PROVIDERS["ollama"]
        elif "localhost:1234" in base_lower or "127.0.0.1:1234" in base_lower:
            return PROVIDERS["vllm"]

        # Parse hostname for custom router (e.g. LiteLLM, OneAPI, vLLM)
        try:
            parsed = urlparse(api_base)
            hostname = parsed.netloc or parsed.path.split("/")[0]
            display_name = hostname.split(":")[0]
            short_name = display_name.split(".")[0]
            return ProviderProfile(
                id="custom",
                name=f"{short_name} ({display_name})" if short_name else "Custom Router",
                default_base=api_base,
                env_key="OPENAI_API_KEY",
                description=f"Router at {api_base}"
            )
        except Exception:
            return PROVIDERS["custom"]

    @staticmethod
    async def get_models_for_provider(provider: ProviderProfile, api_key: str = "", api_base: str = "") -> List[ModelInfo]:
        """Fetch real live models from the {api_base}/models endpoint, with smart fallback."""
        target_base = (api_base or provider.default_base).rstrip("/")
        if not target_base:
            return provider.curated_models or [ModelInfo(id="default-model", name="Default Model")]

        # 1. Try querying /models on the target API base
        try:
            headers = {"Accept": "application/json"}
            if api_key and api_key != "your_api_key_here":
                headers["Authorization"] = f"Bearer {api_key}"
            
            # Special header for OpenRouter
            if "openrouter.ai" in target_base:
                headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NexusAgent"

            models_url = f"{target_base}/models"
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(models_url, headers=headers)
                if resp.status_code == 200:
                    json_data = resp.json()
                    raw_list = json_data.get("data", [])
                    if isinstance(raw_list, list) and raw_list:
                        live_models: List[ModelInfo] = []
                        for m in raw_list:
                            mid = m.get("id")
                            if not mid:
                                continue
                            
                            # Extract context window
                            ctx_raw = (
                                m.get("context_length")
                                or m.get("capabilities", {}).get("contextWindow")
                                or m.get("context_window")
                                or m.get("max_tokens")
                            )
                            ctx_formatted = _format_context_size(ctx_raw)

                            # Tags
                            tag = _detect_tags(mid, m)

                            # Description
                            desc = m.get("owned_by") or m.get("object") or ""

                            live_models.append(ModelInfo(
                                id=mid,
                                name=mid,
                                tag=tag,
                                context=ctx_formatted,
                                description=str(desc)
                            ))

                        if live_models:
                            # Prioritize active model and free/reasoning models
                            current_model = config.MODEL.lower()
                            def sort_key(item: ModelInfo):
                                is_current = (item.id.lower() == current_model)
                                is_free = "free" in item.tag.lower() or "free" in item.id.lower()
                                return (not is_current, not is_free, item.id.lower())

                            live_models.sort(key=sort_key)
                            return live_models
        except Exception:
            pass

        # 2. If Ollama local, try /api/tags
        if provider.is_local or "localhost:11434" in target_base:
            try:
                tags_url = "http://localhost:11434/api/tags"
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(tags_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        models = []
                        for m in data.get("models", []):
                            m_name = m.get("name", "")
                            size_mb = m.get("size", 0) / (1024 * 1024)
                            models.append(ModelInfo(
                                id=m_name,
                                name=m_name,
                                tag="Local",
                                context=f"{size_mb:.0f}MB",
                                description="Local host model"
                            ))
                        if models:
                            return models
            except Exception:
                pass

        # 3. Fallback to curated models if live query didn't yield results
        if provider.curated_models:
            return provider.curated_models

        return [
            ModelInfo(id="default-model", name="Default Model", tag="Custom", context="Auto")
        ]

    @staticmethod
    def update_env_file(key_values: Dict[str, str], env_path: Path):
        """Update or create key-value pairs in .env cleanly."""
        env_path.parent.mkdir(parents=True, exist_ok=True)
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")

        for key, val in key_values.items():
            pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
            if pattern.search(content):
                content = pattern.sub(f"{key}={val}", content)
            else:
                if content and not content.endswith("\n"):
                    content += "\n"
                content += f"{key}={val}\n"

        env_path.write_text(content, encoding="utf-8")
