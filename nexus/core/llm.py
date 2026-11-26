import asyncio
import json
import httpx
from typing import List, Dict, Any, Optional, Callable

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_DEFAULT_RETRY_DELAYS = (1.5, 3.0, 5.0)


class _RetryableAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"API Error ({status_code}): {message}")


def _is_retryable_status(code: int) -> bool:
    return code in _RETRYABLE_STATUS_CODES or 520 <= code <= 530


def sanitize_messages(messages: List[Dict[str, Any]], force_non_empty: bool = False) -> List[Dict[str, Any]]:
    """
    Normalize message dicts so strict OpenAI-compatible routers never reject
    missing/null/empty `content` fields (e.g., 'API Error (400): Content is required').
    """
    sanitized: List[Dict[str, Any]] = []
    for raw in messages:
        msg = dict(raw)
        role = msg.get("role", "user")
        content = msg.get("content")

        if content is None:
            content_str = ""
        elif isinstance(content, str):
            content_str = content
        elif isinstance(content, list):
            # Multimodal content array — preserve as-is
            sanitized.append(msg)
            continue
        else:
            content_str = str(content)

        if role == "assistant" and msg.get("tool_calls"):
            if not content_str.strip():
                content_str = "[calling tools]"
        elif role == "tool":
            if not content_str.strip():
                content_str = "(empty tool output)"
        elif force_non_empty and not content_str.strip():
            content_str = " "

        msg["content"] = content_str
        sanitized.append(msg)
    return sanitized


class LLMClient:
    def __init__(self, api_key: str, api_base: str, model: str, temperature: float = 0.2, max_retries: int = 3):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        on_token: Optional[Callable[[str], None]] = None,
        on_retry: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Send chat completion request with sanitization, SSE streaming, and automatic retry backoff."""
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if "openrouter.ai" in self.api_base:
            headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NexusAgent"
            headers["X-Title"] = "Nexus Agent CLI"

        clean_messages = sanitize_messages(messages)
        last_err: Optional[Exception] = None
        total_attempts = max(1, self.max_retries + 1)

        for attempt in range(total_attempts):
            try:
                if on_token:
                    emitted = [False]

                    def _tracked_token(tok: str):
                        if tok and tok.strip():
                            emitted[0] = True
                        on_token(tok)

                    try:
                        return await self._stream_completion(
                            url, headers, clean_messages, tools, tool_choice, _tracked_token
                        )
                    except _RetryableAPIError as stream_retry_err:
                        if emitted[0]:
                            raise stream_retry_err
                        # On final attempt, give non-streaming one shot before failing
                        if attempt >= total_attempts - 1:
                            return await self._standard_completion(url, headers, clean_messages, tools, tool_choice)
                        raise stream_retry_err
                    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.TransportError):
                        if emitted[0]:
                            raise
                        raise
                    except Exception as stream_err:
                        if emitted[0]:
                            raise stream_err
                        # Stream unsupported or returned 400 -> fallback immediately to non-streaming
                        return await self._standard_completion(url, headers, clean_messages, tools, tool_choice)

                return await self._standard_completion(url, headers, clean_messages, tools, tool_choice)

            except _RetryableAPIError as e:
                last_err = e
                if attempt >= total_attempts - 1:
                    raise RuntimeError(str(e))
                delay = _DEFAULT_RETRY_DELAYS[min(attempt, len(_DEFAULT_RETRY_DELAYS) - 1)]
                if on_retry:
                    try:
                        on_retry(attempt + 1, self.max_retries, f"HTTP {e.status_code}")
                    except Exception:
                        pass
                await asyncio.sleep(delay)

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.TransportError) as e:
                last_err = e
                if attempt >= total_attempts - 1:
                    raise RuntimeError(f"Network error after retries: {type(e).__name__}: {e}")
                delay = _DEFAULT_RETRY_DELAYS[min(attempt, len(_DEFAULT_RETRY_DELAYS) - 1)]
                if on_retry:
                    try:
                        on_retry(attempt + 1, self.max_retries, type(e).__name__)
                    except Exception:
                        pass
                await asyncio.sleep(delay)

            except RuntimeError as e:
                err_low = str(e).lower()
                if "content is required" in err_low and attempt == 0:
                    # Force non-empty whitespace on every message and retry once immediately
                    clean_messages = sanitize_messages(messages, force_non_empty=True)
                    if on_retry:
                        try:
                            on_retry(1, 1, "Sanitizing empty content")
                        except Exception:
                            pass
                    continue
                raise

        if last_err:
            raise last_err
        raise RuntimeError("Unknown LLM completion failure")

    async def _standard_completion(
        self,
        url: str,
        headers: Dict[str, str],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: str,
    ) -> Dict[str, Any]:
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
                    err_obj = error_json.get("error", {})
                    err_msg = err_obj.get("message", error_body) if isinstance(err_obj, dict) else str(err_obj)
                except Exception:
                    err_msg = error_body
                if _is_retryable_status(response.status_code):
                    raise _RetryableAPIError(response.status_code, err_msg)
                raise RuntimeError(f"API Error ({response.status_code}): {err_msg}")

            data = response.json()
            if isinstance(data, dict) and data.get("error") and not data.get("choices"):
                err_obj = data["error"]
                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                err_code = int(err_obj.get("code", 502)) if isinstance(err_obj, dict) and str(err_obj.get("code", "")).isdigit() else 502
                if _is_retryable_status(err_code):
                    raise _RetryableAPIError(err_code, err_msg)
                raise RuntimeError(f"API Error ({err_code}): {err_msg}")

            choice = data["choices"][0]
            msg = dict(choice["message"])
            if msg.get("content") is None:
                msg["content"] = ""
            return msg

    async def _stream_completion(
        self,
        url: str,
        headers: Dict[str, str],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: str,
        on_token: Callable[[str], None],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        accumulated_content = ""
        tool_calls_dict: Dict[int, Dict[str, Any]] = {}

        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    err_raw = await resp.aread()
                    err_text = err_raw.decode("utf-8", errors="replace")
                    try:
                        err_json = json.loads(err_text)
                        err_obj = err_json.get("error", {})
                        err_msg = err_obj.get("message", err_text) if isinstance(err_obj, dict) else str(err_obj)
                    except Exception:
                        err_msg = err_text
                    if _is_retryable_status(resp.status_code):
                        raise _RetryableAPIError(resp.status_code, err_msg)
                    raise RuntimeError(f"API Error ({resp.status_code}): {err_msg}")

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if isinstance(chunk, dict) and chunk.get("error") and not chunk.get("choices"):
                                err_obj = chunk["error"]
                                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                                raise _RetryableAPIError(502, err_msg)

                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or choices[0].get("message") or {}

                            text_chunk = delta.get("content")
                            if text_chunk:
                                accumulated_content += text_chunk
                                on_token(text_chunk)

                            tc_chunks = delta.get("tool_calls", [])
                            for tc in tc_chunks:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_dict:
                                    tool_calls_dict[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": "function",
                                        "function": {
                                            "name": tc.get("function", {}).get("name", ""),
                                            "arguments": tc.get("function", {}).get("arguments", ""),
                                        },
                                    }
                                else:
                                    if tc.get("id"):
                                        tool_calls_dict[idx]["id"] += tc["id"]
                                    fn = tc.get("function", {})
                                    if fn.get("name"):
                                        tool_calls_dict[idx]["function"]["name"] += fn["name"]
                                    if fn.get("arguments"):
                                        tool_calls_dict[idx]["function"]["arguments"] += fn["arguments"]
                        except _RetryableAPIError:
                            raise
                        except Exception:
                            continue

        final_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": accumulated_content if accumulated_content else ("[calling tools]" if tool_calls_dict else ""),
        }
        if tool_calls_dict:
            final_msg["tool_calls"] = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())]

        return final_msg
