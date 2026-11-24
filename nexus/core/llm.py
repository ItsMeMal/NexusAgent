import httpx
import json
from typing import List, Dict, Any, Optional, Callable

class LLMClient:
    def __init__(self, api_key: str, api_base: str, model: str, temperature: float = 0.2):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.temperature = temperature

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        on_token: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Send chat completion request with real-time SSE token streaming when on_token is provided."""
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        if "openrouter.ai" in self.api_base:
            headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NexusAgent"
            headers["X-Title"] = "Nexus Agent CLI"

        # Attempt streaming if on_token callback is provided
        if on_token:
            try:
                return await self._stream_completion(url, headers, messages, tools, tool_choice, on_token)
            except Exception:
                # If router doesn't support streaming for this model, fallback smoothly to standard request
                pass

        # Standard non-streaming fallback
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                error_body = response.text
                try:
                    error_json = response.json()
                    err_msg = error_json.get("error", {}).get("message", error_body)
                except Exception:
                    err_msg = error_body
                raise RuntimeError(f"API Error ({response.status_code}): {err_msg}")

            data = response.json()
            choice = data["choices"][0]
            return choice["message"]

    async def _stream_completion(
        self,
        url: str,
        headers: Dict[str, str],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: str,
        on_token: Callable[[str], None]
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        accumulated_content = ""
        tool_calls_dict: Dict[int, Dict[str, Any]] = {}

        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    err_text = await resp.aread()
                    raise RuntimeError(f"Stream error {resp.status_code}: {err_text.decode('utf-8', errors='replace')}")

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})

                            # Content streaming
                            text_chunk = delta.get("content")
                            if text_chunk:
                                accumulated_content += text_chunk
                                on_token(text_chunk)

                            # Tool call streaming
                            tc_chunks = delta.get("tool_calls", [])
                            for tc in tc_chunks:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_dict:
                                    tool_calls_dict[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": "function",
                                        "function": {
                                            "name": tc.get("function", {}).get("name", ""),
                                            "arguments": tc.get("function", {}).get("arguments", "")
                                        }
                                    }
                                else:
                                    if tc.get("id"):
                                        tool_calls_dict[idx]["id"] += tc["id"]
                                    fn = tc.get("function", {})
                                    if fn.get("name"):
                                        tool_calls_dict[idx]["function"]["name"] += fn["name"]
                                    if fn.get("arguments"):
                                        tool_calls_dict[idx]["function"]["arguments"] += fn["arguments"]
                        except Exception:
                            continue

        final_msg: Dict[str, Any] = {"role": "assistant"}
        if accumulated_content:
            final_msg["content"] = accumulated_content
        if tool_calls_dict:
            final_msg["tool_calls"] = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())]

        return final_msg
