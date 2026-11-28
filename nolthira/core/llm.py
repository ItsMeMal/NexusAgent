import asyncio
import json
import httpx
from typing import List, Dict, Any, Optional, Callable

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_DEFAULT_RETRY_DELAYS = (1.5, 3.0, 5.0)


def normalize_token_usage(raw: Any) -> Optional[Dict[str, int]]:
    """Normalize OpenAI-compatible token usage fields; None means not supplied."""
    if not isinstance(raw, dict):
        return None

    def read_int(*keys: str) -> int:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                return int(value)
        return 0

    prompt = read_int("prompt_tokens", "input_tokens", "promptTokens", "inputTokens")
    completion = read_int("completion_tokens", "output_tokens", "completionTokens", "outputTokens")
    total = read_int("total_tokens", "totalTokens") or prompt + completion
    if prompt == 0 and completion == 0 and total == 0:
        return None
    if prompt == 0 and total >= completion:
        prompt = total - completion
    if completion == 0 and total >= prompt:
        completion = total - prompt
    return {"input_tokens": prompt, "output_tokens": completion, "total_tokens": total}


def _estimate_text_tokens(value: Any) -> int:
    """Character-based estimate, displayed as estimated rather than provider-reported."""
    if isinstance(value, str):
        return (len(value) + 3) // 4
    if isinstance(value, dict):
        return sum(_estimate_text_tokens(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_estimate_text_tokens(item) for item in value)
    return 0


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
    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        temperature: float = 0.2,
        max_retries: int = 3,
        token_provider: Optional[Callable[[], Any]] = None,
        on_usage: Optional[Callable[[Dict[str, Any]], None]] = None,
        context_window: int = 0,
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.token_provider = token_provider
        self.on_usage = on_usage
        self.context_window = max(0, int(context_window or 0))
        self.last_usage: Dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "source": "unavailable"
        }
        self.session_usage: Dict[str, int] = {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0, "estimated_requests": 0
        }

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        on_token: Optional[Callable[[str], None]] = None,
        on_retry: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Send chat completion request with token telemetry and refreshable credentials."""
        if self.token_provider is not None:
            refreshed_key = await self.token_provider()
            if not isinstance(refreshed_key, str) or not refreshed_key.strip():
                raise RuntimeError("Provider authentication returned an empty access token.")
            self.api_key = refreshed_key
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if "openrouter.ai" in self.api_base:
            headers["HTTP-Referer"] = "https://github.com/ItsMeMal/NolthiraAgent"
            headers["X-Title"] = "Nolthira Agent CLI"

        clean_messages = sanitize_messages(messages)

        async def _finalize(response_msg: Dict[str, Any]) -> Dict[str, Any]:
            usage = normalize_token_usage(response_msg.pop("_nolthira_usage", None))
            source = "api_reported" if usage else "estimated"
            if usage is None:
                input_tokens = _estimate_text_tokens(clean_messages)
                output_tokens = _estimate_text_tokens({
                    "content": response_msg.get("content", ""),
                    "tool_calls": response_msg.get("tool_calls", []),
                })
                usage = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                self.session_usage[key] += int(usage.get(key, 0))
            self.session_usage["requests"] += 1
            if source == "estimated":
                self.session_usage["estimated_requests"] += 1
            self.last_usage = {
                **usage,
                "source": source,
                "model": self.model,
                "context_window": self.context_window,
                "session": dict(self.session_usage),
            }
            if self.on_usage:
                try:
                    self.on_usage(dict(self.last_usage))
                except Exception:
                    pass
            return response_msg

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
                        streamed = await self._stream_completion(
                            url, headers, clean_messages, tools, tool_choice, _tracked_token
                        )
                        return await _finalize(streamed)
                    except _RetryableAPIError as stream_retry_err:
                        if emitted[0]:
                            raise stream_retry_err
                        # On final attempt, give non-streaming one shot before failing
                        if attempt >= total_attempts - 1:
                            standard = await self._standard_completion(url, headers, clean_messages, tools, tool_choice)
                            return await _finalize(standard)
                        raise stream_retry_err
                    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.TransportError):
                        if emitted[0]:
                            raise
                        raise
                    except Exception as stream_err:
                        if emitted[0]:
                            raise stream_err
                        # Stream unsupported or returned 400 -> fallback immediately to non-streaming
                        standard = await self._standard_completion(url, headers, clean_messages, tools, tool_choice)
                        return await _finalize(standard)

                standard = await self._standard_completion(url, headers, clean_messages, tools, tool_choice)
                return await _finalize(standard)

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
            if isinstance(data.get("usage"), dict):
                msg["_nolthira_usage"] = data["usage"]
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
        # Mallss Nexus Route emits final usage in choices[0].usage; standard
        # OpenAI providers may emit the usage-only top-level SSE chunk.
        stream_usage: Optional[Dict[str, Any]] = None
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
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if isinstance(chunk, dict) and chunk.get("error") and not chunk.get("choices"):
                                err_obj = chunk["error"]
                                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                                raise _RetryableAPIError(502, err_msg)

                            if isinstance(chunk.get("usage"), dict):
                                stream_usage = chunk["usage"]
                            choices = chunk.get("choices", [])
                            if choices and isinstance(choices[0].get("usage"), dict):
                                stream_usage = choices[0]["usage"]
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or choices[0].get("message") or {}

                            text_chunk = delta.get("content")
                            if text_chunk:
                                accumulated_content += text_chunk
                                on_token(text_chunk)

                            tc_chunks = delta.get("tool_calls") or []
                            for tc in tc_chunks:
                                if not isinstance(tc, dict):
                                    continue
                                raw_idx = tc.get("index")
                                tc_id_chunk = tc.get("id") or ""
                                if raw_idx is not None:
                                    idx = raw_idx
                                elif not tool_calls_dict:
                                    idx = 0
                                elif tc_id_chunk and tc_id_chunk != tool_calls_dict.get(max(tool_calls_dict), {}).get("id"):
                                    idx = max(tool_calls_dict) + 1
                                else:
                                    idx = max(tool_calls_dict)

                                fn = tc.get("function") or {}
                                fn_name_chunk = fn.get("name") or ""
                                fn_args_chunk = fn.get("arguments")
                                if fn_args_chunk is None:
                                    fn_args_chunk = ""
                                elif not isinstance(fn_args_chunk, str):
                                    fn_args_chunk = json.dumps(fn_args_chunk)

                                if idx not in tool_calls_dict:
                                    tool_calls_dict[idx] = {
                                        "id": tc_id_chunk,
                                        "type": "function",
                                        "function": {
                                            "name": fn_name_chunk,
                                            "arguments": fn_args_chunk,
                                        },
                                    }
                                else:
                                    cur_id = tool_calls_dict[idx].get("id") or ""
                                    if tc_id_chunk:
                                        if not cur_id:
                                            tool_calls_dict[idx]["id"] = tc_id_chunk
                                        elif tc_id_chunk == cur_id:
                                            pass  # repeated ID across chunks
                                        elif tc_id_chunk.startswith(cur_id):
                                            tool_calls_dict[idx]["id"] = tc_id_chunk
                                        else:
                                            tool_calls_dict[idx]["id"] = cur_id + tc_id_chunk

                                    cur_name = tool_calls_dict[idx]["function"].get("name") or ""
                                    if fn_name_chunk:
                                        if not cur_name:
                                            tool_calls_dict[idx]["function"]["name"] = fn_name_chunk
                                        elif fn_name_chunk == cur_name:
                                            pass  # repeated name across chunks (common on proxies)
                                        elif fn_name_chunk.startswith(cur_name):
                                            tool_calls_dict[idx]["function"]["name"] = fn_name_chunk
                                        else:
                                            tool_calls_dict[idx]["function"]["name"] = cur_name + fn_name_chunk

                                    if fn_args_chunk:
                                        tool_calls_dict[idx]["function"]["arguments"] = (
                                            (tool_calls_dict[idx]["function"].get("arguments") or "") + fn_args_chunk
                                        )
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
        if stream_usage:
            final_msg["_nolthira_usage"] = stream_usage

        return final_msg
