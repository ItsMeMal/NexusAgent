import os
import re
import json
import asyncio
import datetime
import httpx
from urllib.parse import urlparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from ..config import config

@dataclass
class ModelInfo:
    id: str
    name: str
    tag: str = "Standard"
    context: str = "128k"
    description: str = ""
    status: str = "unchecked"  # "active" | "down" | "unchecked"
    status_reason: str = ""

@dataclass
class ProviderProfile:
    id: str
    name: str
    default_base: str
    env_key: str
    description: str
    is_local: bool = False
    curated_models: List[ModelInfo] = field(default_factory=list)
    # New cloud profiles use the exact Chat Completions shape consumed by LLMClient.
    protocol: str = "unverified"

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
    # OpenAI-compatible cloud inference providers. Model IDs are discovered from
    # each provider's /models endpoint instead of hard-coding a quickly-stale catalog.
    "cerebras": ProviderProfile(
        id="cerebras",
        name="Cerebras",
        default_base="https://api.cerebras.ai/v1",
        env_key="CEREBRAS_API_KEY",
        description="Cerebras Inference API (OpenAI-compatible Chat Completions)",
        protocol="openai-chat-completions",
    ),
    "sambanova": ProviderProfile(
        id="sambanova",
        name="SambaNova Cloud",
        default_base="https://api.sambanova.ai/v1",
        env_key="SAMBANOVA_API_KEY",
        description="SambaNova Cloud inference (OpenAI-compatible Chat Completions)",
        protocol="openai-chat-completions",
    ),
    "deepinfra": ProviderProfile(
        id="deepinfra",
        name="DeepInfra",
        default_base="https://api.deepinfra.com/v1/openai",
        env_key="DEEPINFRA_API_KEY",
        description="Open-model inference through DeepInfra's OpenAI-compatible API",
        protocol="openai-chat-completions",
    ),
    "siliconflow": ProviderProfile(
        id="siliconflow",
        name="SiliconFlow",
        default_base="https://api.siliconflow.com/v1",
        env_key="SILICONFLOW_API_KEY",
        description="SiliconFlow hosted open models (OpenAI-compatible API)",
        protocol="openai-chat-completions",
    ),
    "novita": ProviderProfile(
        id="novita",
        name="Novita AI",
        default_base="https://api.novita.ai/v3/openai",
        env_key="NOVITA_API_KEY",
        description="Novita AI inference API (OpenAI-compatible Chat Completions)",
        protocol="openai-chat-completions",
    ),
    "nebius": ProviderProfile(
        id="nebius",
        name="Nebius Token Factory",
        default_base="https://api.tokenfactory.nebius.com/v1",
        env_key="NEBIUS_TOKEN_FACTORY_KEY",
        description="Nebius Token Factory OpenAI-compatible inference",
        protocol="openai-chat-completions",
    ),
    "hyperbolic": ProviderProfile(
        id="hyperbolic",
        name="Hyperbolic",
        default_base="https://api.hyperbolic.ai/inference/v1",
        env_key="HYPERBOLIC_API_KEY",
        description="Hyperbolic Flux inference API (OpenAI-compatible Chat Completions)",
        protocol="openai-chat-completions",
    ),
    "nvidia_nim": ProviderProfile(
        id="nvidia_nim",
        name="NVIDIA NIM",
        default_base="https://integrate.api.nvidia.com/v1",
        env_key="NVIDIA_API_KEY",
        description="NVIDIA hosted NIM inference API (OpenAI-compatible)",
        protocol="openai-chat-completions",
    ),
    "moonshot": ProviderProfile(
        id="moonshot",
        name="Moonshot AI (Kimi)",
        default_base="https://api.moonshot.ai/v1",
        env_key="MOONSHOT_API_KEY",
        description="Moonshot AI / Kimi OpenAI-compatible API",
        protocol="openai-chat-completions",
    ),
    "alibaba_model_studio": ProviderProfile(
        id="alibaba_model_studio",
        name="Alibaba Cloud Model Studio (Qwen)",
        default_base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        env_key="DASHSCOPE_API_KEY",
        description="Alibaba Model Studio OpenAI-compatible endpoint (regional API keys)",
        protocol="openai-chat-completions",
    ),
    "zai": ProviderProfile(
        id="zai",
        name="Z.ai (GLM)",
        default_base="https://api.z.ai/api/paas/v4",
        env_key="ZAI_API_KEY",
        description="Z.ai GLM general API (OpenAI-compatible; not the Coding Plan endpoint)",
        protocol="openai-chat-completions",
    ),
    "minimax": ProviderProfile(
        id="minimax",
        name="MiniMax",
        default_base="https://api.minimax.io/v1",
        env_key="MINIMAX_API_KEY",
        description="MiniMax OpenAI-compatible text generation API",
        protocol="openai-chat-completions",
    ),
    "byteplus": ProviderProfile(
        id="byteplus",
        name="BytePlus ModelArk",
        default_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        env_key="ARK_API_KEY",
        description="BytePlus ModelArk OpenAI-compatible inference (Singapore endpoint)",
        protocol="openai-chat-completions",
    ),
    "huggingface": ProviderProfile(
        id="huggingface",
        name="Hugging Face Inference Providers",
        default_base="https://router.huggingface.co/v1",
        env_key="HF_TOKEN",
        description="Unified OpenAI-compatible chat router; use Hub model IDs and provider suffixes",
        protocol="openai-chat-completions",
    ),
    # Bedrock Mantle exposes OpenAI-compatible /chat/completions and /models.
    # This profile uses an API key; AWS SigV4 credentials are not implemented here.
    "bedrock": ProviderProfile(
        id="bedrock",
        name="Amazon Bedrock (Mantle API Key)",
        default_base="https://bedrock-mantle.us-east-1.api.aws/v1",
        env_key="AWS_BEDROCK_API_KEY",
        description="Bedrock Mantle OpenAI-compatible API-key endpoint (default region: us-east-1)",
        protocol="openai-chat-completions",
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

_DOWN_STATUS_VALUES = {
    "down", "offline", "inactive", "disabled", "unavailable",
    "dead", "error", "maintenance", "deprecated", "suspended",
    "paused", "failed", "unhealthy",
}
_ACTIVE_STATUS_VALUES = {
    "active", "online", "available", "healthy", "ok", "up", "ready", "enabled",
}
_DEFAULT_HEALTH_CACHE_PATH = Path.home() / ".nexus" / "model_health.json"


class ModelHealthCache:
    """Persists daily per-provider model health (aktif / down / belum dicek)."""

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path or _DEFAULT_HEALTH_CACHE_PATH
        self._data: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.cache_path.exists():
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
        except Exception:
            self._data = {}

    def save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _today(today_str: Optional[str] = None) -> str:
        return today_str or datetime.date.today().isoformat()

    def get(self, api_base: str, model_id: str, today_str: Optional[str] = None) -> Optional[Dict[str, str]]:
        base_key = api_base.rstrip("/")
        entry = self._data.get(base_key, {}).get(model_id)
        if not isinstance(entry, dict):
            return None
        today = self._today(today_str)
        # Only trust cached status from the same calendar day; next day ("besoknya") must re-check!
        if entry.get("date") != today:
            return None
        return entry

    def set(self, api_base: str, model_id: str, status: str, reason: str = "", today_str: Optional[str] = None) -> None:
        base_key = api_base.rstrip("/")
        if base_key not in self._data or not isinstance(self._data[base_key], dict):
            self._data[base_key] = {}
        self._data[base_key][model_id] = {
            "status": status,
            "date": self._today(today_str),
            "reason": reason[:160],
        }


def _inspect_provider_model_status(m_dict: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Inspect metadata fields from provider /models response for explicit active/down state."""
    if not isinstance(m_dict, dict):
        return None, ""

    for key in ("status", "state", "health", "availability", "provider_status"):
        val = m_dict.get(key)
        if isinstance(val, str) and val.strip():
            low = val.strip().lower()
            if low in _DOWN_STATUS_VALUES:
                return "down", f"Provider status: {val}"
            if low in _ACTIVE_STATUS_VALUES:
                return "active", f"Provider status: {val}"

    for bool_false_key in ("active", "is_active", "enabled", "is_enabled", "available", "is_available", "healthy", "online"):
        if bool_false_key in m_dict and m_dict[bool_false_key] is False:
            return "down", f"Provider {bool_false_key}=false"

    for bool_true_key in ("down", "is_down", "disabled", "deprecated", "is_deprecated", "offline"):
        if bool_true_key in m_dict and m_dict[bool_true_key] is True:
            return "down", f"Provider {bool_true_key}=true"

    return None, ""


async def _probe_model_health(
    client: httpx.AsyncClient,
    target_base: str,
    api_key: str,
    model_id: str,
    use_x_api_key: bool = False,
) -> Tuple[str, str]:
    """Probe {target_base}/chat/completions lightly to test if model is aktif or down/mati."""
    url = f"{target_base}/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        if use_x_api_key:
            headers["x-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    if "openrouter.ai" in target_base:
        headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NexusAgent"
        headers["X-Title"] = "Nexus Agent CLI"

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }

    try:
        resp = await client.post(url, headers=headers, json=payload)
        code = resp.status_code

        if code == 200:
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get("error") and not body.get("choices"):
                    err_txt = str(body.get("error")).lower()
                    if any(w in err_txt for w in ("down", "unavailable", "offline", "disabled", "not found", "does not exist", "maintenance", "no available")):
                        return "down", f"API error: {str(body.get('error'))[:80]}"
                    return "unchecked", "API returned non-fatal error"
            except Exception:
                pass
            return "active", "200 OK"

        body_text = (resp.text or "").lower()

        if code in (404, 410, 500, 502, 503, 504) or 520 <= code <= 530:
            return "down", f"HTTP {code}"

        if code == 400:
            if any(w in body_text for w in ("not found", "does not exist", "no such model", "unknown model", "model is down", "unavailable", "disabled", "offline", "decommissioned", "deprecated")):
                return "down", "HTTP 400: model unavailable"
            if any(w in body_text for w in ("max_tokens", "max_completion_tokens", "temperature", "unsupported parameter")):
                return "active", "Endpoint OK (param hint)"
            return "unchecked", "HTTP 400"

        if code in (401, 403, 429):
            return "unchecked", f"HTTP {code} (auth/rate-limit)"

        return "unchecked", f"HTTP {code}"
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        return "down", f"Connection failed: {type(exc).__name__}"
    except Exception:
        return "unchecked", "Probe error"


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
        host = (urlparse(api_base).hostname or "").lower()

        # Match dedicated provider hostnames before falling back to legacy profiles.
        provider_hosts = (
            (("api.cerebras.ai",), "cerebras"),
            (("api.sambanova.ai",), "sambanova"),
            (("api.deepinfra.com",), "deepinfra"),
            (("api.siliconflow.com", "api.siliconflow.cn"), "siliconflow"),
            (("api.novita.ai",), "novita"),
            (("api.tokenfactory.nebius.com",), "nebius"),
            (("api.hyperbolic.ai", "api.hyperbolic.xyz"), "hyperbolic"),
            (("integrate.api.nvidia.com",), "nvidia_nim"),
            (("api.moonshot.ai", "api.moonshot.cn"), "moonshot"),
            (("api.z.ai",), "zai"),
            (("api.minimax.io",), "minimax"),
            (("router.huggingface.co",), "huggingface"),
        )
        for domains, provider_id in provider_hosts:
            if any(host == domain or host.endswith("." + domain) for domain in domains):
                return PROVIDERS[provider_id]

        if "dashscope" in host and "aliyuncs.com" in host:
            return PROVIDERS["alibaba_model_studio"]
        if host.endswith("bytepluses.com") or host.endswith("byteplusapi.com"):
            return PROVIDERS["byteplus"]
        if host.startswith("bedrock-mantle.") and host.endswith(".api.aws"):
            return PROVIDERS["bedrock"]

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
    async def get_models_with_health(
        provider: ProviderProfile,
        api_key: str = "",
        api_base: str = "",
        check_health: bool = True,
        force_refresh: bool = False,
        health_cache_path: Optional[Path] = None,
        today_str: Optional[str] = None,
        max_probes: int = 24,
    ) -> Tuple[List[ModelInfo], Dict[str, Any]]:
        """
        Fetch live models from {api_base}/models, classify health (active / down / unchecked),
        exclude models that are down today (re-checked automatically next day / on force_refresh),
        and return (usable_models, stats).
        """
        target_base = (api_base or provider.default_base).rstrip("/")
        stats: Dict[str, Any] = {
            "active_count": 0,
            "unchecked_count": 0,
            "down_excluded": 0,
            "down_models": [],
        }
        if not target_base:
            models = list(provider.curated_models) or [ModelInfo(id="default-model", name="Default Model")]
            stats["unchecked_count"] = len(models)
            return models, stats

        # Collect candidate keys to authenticate against /models
        candidate_keys: List[str] = []
        if api_key and api_key != "your_api_key_here":
            candidate_keys.append(api_key)
        for env_var in ("MALLSS_NEXUS_API_KEY", "NEXUS_API_KEY", "OPENAI_API_KEY"):
            val = os.getenv(env_var, "").strip()
            if val and val != "your_api_key_here" and val not in candidate_keys:
                candidate_keys.append(val)

        # Also inspect config.ENV_PATH directly as extra fallback
        try:
            from dotenv import dotenv_values
            if hasattr(config, "ENV_PATH") and config.ENV_PATH.exists():
                file_vals = dotenv_values(config.ENV_PATH)
                for k in ("OPENAI_API_KEY", "NEXUS_API_KEY", "MALLSS_NEXUS_API_KEY"):
                    v = (file_vals.get(k) or "").strip()
                    if v and v != "your_api_key_here" and v not in candidate_keys:
                        candidate_keys.append(v)
        except Exception:
            pass

        if not candidate_keys:
            candidate_keys.append("")

        cache = ModelHealthCache(health_cache_path)

        # 1. Try querying /models on the target API base
        models_url = f"{target_base}/models"
        for candidate_key in candidate_keys:
            try:
                headers = {"Accept": "application/json"}
                if candidate_key:
                    headers["Authorization"] = f"Bearer {candidate_key}"

                if "openrouter.ai" in target_base:
                    headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NexusAgent"

                use_x_api_key = False
                async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                    resp = await client.get(models_url, headers=headers)
                    if resp.status_code in (401, 403) and candidate_key:
                        resp = await client.get(models_url, headers={"Accept": "application/json", "x-api-key": candidate_key})
                        if resp.status_code == 200:
                            use_x_api_key = True

                    if resp.status_code == 200:
                        json_data = resp.json()
                        raw_list = []
                        if isinstance(json_data, list):
                            raw_list = json_data
                        elif isinstance(json_data, dict):
                            raw_list = json_data.get("data") or json_data.get("models") or []
                            if not isinstance(raw_list, list):
                                raw_list = []

                        if raw_list:
                            parsed_items: List[Tuple[ModelInfo, Dict[str, Any]]] = []
                            for m in raw_list:
                                if isinstance(m, str):
                                    mid = m
                                    m_dict = {}
                                elif isinstance(m, dict):
                                    mid = m.get("id") or m.get("name") or m.get("model")
                                    m_dict = m
                                else:
                                    continue

                                if not mid:
                                    continue

                                ctx_raw = (
                                    m_dict.get("context_length")
                                    or (m_dict.get("capabilities") or {}).get("contextWindow")
                                    or m_dict.get("context_window")
                                    or m_dict.get("max_tokens")
                                )
                                ctx_formatted = _format_context_size(ctx_raw)
                                tag = _detect_tags(mid, m_dict)
                                desc = m_dict.get("owned_by") or m_dict.get("object") or ""

                                info = ModelInfo(
                                    id=mid,
                                    name=mid,
                                    tag=tag,
                                    context=ctx_formatted,
                                    description=str(desc),
                                    status="unchecked",
                                )
                                parsed_items.append((info, m_dict))

                            if parsed_items:
                                # Step A: Check explicit provider metadata + daily health cache
                                to_probe: List[ModelInfo] = []
                                live_models: List[ModelInfo] = []

                                for info, m_dict in parsed_items:
                                    meta_status, meta_reason = _inspect_provider_model_status(m_dict)
                                    if meta_status == "down":
                                        cache.set(target_base, info.id, "down", meta_reason, today_str=today_str)
                                        stats["down_excluded"] += 1
                                        stats["down_models"].append(info.id)
                                        continue

                                    cached = None if force_refresh else cache.get(target_base, info.id, today_str=today_str)
                                    if cached:
                                        c_status = cached.get("status", "unchecked")
                                        c_reason = cached.get("reason", "")
                                        if c_status == "down":
                                            # Already confirmed down today -> exclude until tomorrow (besoknya)
                                            stats["down_excluded"] += 1
                                            stats["down_models"].append(info.id)
                                            continue
                                        if c_status == "active":
                                            info.status = "active"
                                            info.status_reason = c_reason or "Cached active"
                                            live_models.append(info)
                                            continue

                                    if meta_status == "active":
                                        info.status = "active"
                                        info.status_reason = meta_reason
                                        cache.set(target_base, info.id, "active", meta_reason, today_str=today_str)
                                        live_models.append(info)
                                        continue

                                    # Eligible for live probe (or stays unchecked if over probe cap)
                                    live_models.append(info)
                                    to_probe.append(info)

                                # Step B: Live concurrent probe for unchecked models
                                if check_health and to_probe:
                                    # Prioritize current model & free/popular models within probe cap
                                    cur_low = (config.MODEL or "").lower()
                                    to_probe.sort(key=lambda x: (
                                        x.id.lower() != cur_low,
                                        "free" not in x.tag.lower() and "free" not in x.id.lower(),
                                        x.id.lower(),
                                    ))
                                    probe_targets = to_probe[:max_probes]
                                    sem = asyncio.Semaphore(6)

                                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as probe_client:
                                        async def _run_probe_with_client(item: ModelInfo):
                                            async with sem:
                                                st, rsn = await _probe_model_health(
                                                    probe_client, target_base, candidate_key, item.id, use_x_api_key=use_x_api_key
                                                )
                                                item.status = st
                                                item.status_reason = rsn
                                                if st in ("active", "down"):
                                                    cache.set(target_base, item.id, st, rsn, today_str=today_str)

                                        await asyncio.gather(*[_run_probe_with_client(m) for m in probe_targets], return_exceptions=True)

                                    # Filter out newly confirmed down models!
                                    filtered_models: List[ModelInfo] = []
                                    for m in live_models:
                                        if m.status == "down":
                                            stats["down_excluded"] += 1
                                            if m.id not in stats["down_models"]:
                                                stats["down_models"].append(m.id)
                                        else:
                                            filtered_models.append(m)
                                    live_models = filtered_models

                                cache.save()

                                current_model = (config.MODEL or "").lower()
                                def sort_key(item: ModelInfo):
                                    is_current = (item.id.lower() == current_model)
                                    is_active_health = (item.status == "active")
                                    is_free = "free" in item.tag.lower() or "free" in item.id.lower()
                                    return (not is_current, not is_active_health, not is_free, item.id.lower())

                                live_models.sort(key=sort_key)
                                stats["active_count"] = sum(1 for m in live_models if m.status == "active")
                                stats["unchecked_count"] = sum(1 for m in live_models if m.status == "unchecked")
                                return live_models, stats
            except Exception:
                continue

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
                                description="Local host model",
                                status="active",
                                status_reason="Ollama local daemon",
                            ))
                        if models:
                            stats["active_count"] = len(models)
                            return models, stats
            except Exception:
                pass

        # 3. Fallback to curated models if live query didn't yield results
        if provider.curated_models:
            res = [
                ModelInfo(
                    id=m.id, name=m.name, tag=m.tag, context=m.context,
                    description=m.description, status="unchecked",
                )
                for m in provider.curated_models
            ]
            stats["unchecked_count"] = len(res)
            return res, stats

        fallback_models: List[ModelInfo] = []
        if config.MODEL and config.MODEL != "default-model":
            fallback_models.append(ModelInfo(
                id=config.MODEL,
                name=config.MODEL,
                tag="Active",
                context="Auto",
                description="Current active model",
                status="unchecked",
            ))
        fallback_models.append(
            ModelInfo(id="default-model", name="Default Model", tag="Custom", context="Auto", status="unchecked")
        )
        stats["unchecked_count"] = len(fallback_models)
        return fallback_models, stats

    @staticmethod
    async def get_models_for_provider(
        provider: ProviderProfile,
        api_key: str = "",
        api_base: str = "",
        check_health: bool = True,
        force_refresh: bool = False,
    ) -> List[ModelInfo]:
        """Fetch live models from {api_base}/models, excluding down models."""
        models, _ = await ProviderManager.get_models_with_health(
            provider=provider,
            api_key=api_key,
            api_base=api_base,
            check_health=check_health,
            force_refresh=force_refresh,
        )
        return models

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
