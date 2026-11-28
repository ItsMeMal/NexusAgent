import re
import json
import warnings
import httpx
from typing import List, Dict, Any, Optional, Union
from .base import Tool

# Suppress runtime warnings from duckduckgo_search renaming
warnings.filterwarnings("ignore", category=RuntimeWarning)

def get_web_tools():
    async def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for up-to-date information."""
        if not query or not str(query).strip():
            return "Error: Search query cannot be empty."

        clean_query = str(query).strip()

        # 1. Try DuckDuckGo via ddgs / duckduckgo_search
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    from ddgs import DDGS
                except ImportError:
                    from duckduckgo_search import DDGS

                with DDGS() as ddgs:
                    results = list(ddgs.text(clean_query, max_results=max_results))

                if results:
                    output = [f"Search Results for '{clean_query}':"]
                    for i, r in enumerate(results, 1):
                        title = r.get("title", "No Title")
                        href = r.get("href", "")
                        body = r.get("body", "")
                        output.append(f"{i}. {title}\n   URL: {href}\n   Snippet: {body}")
                    return "\n\n".join(output)
        except Exception:
            pass

        # 2. Resilient fallback via DuckDuckGo HTML endpoint
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(f"https://html.duckduckgo.com/html/?q={httpx.URL(clean_query)}")
                if resp.status_code == 200:
                    text = resp.text
                    links = re.findall(r'<a class="result__snippet[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text)
                    if links:
                        out = [f"Search Results for '{clean_query}':"]
                        for link, snippet in links[:max_results]:
                            clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                            out.append(f"- URL: {link}\n  Snippet: {clean_snippet}")
                        return "\n\n".join(out)
        except Exception:
            pass

        return f"No web search results found for: '{clean_query}'"

    async def web_extract(urls: Optional[Any] = None, url: Optional[str] = None, **kwargs) -> str:
        """Fetch and extract readable plain text content from URLs."""
        raw_input = urls if urls is not None else (url if url is not None else kwargs.get("link", ""))

        target_urls: List[str] = []

        if isinstance(raw_input, list):
            for item in raw_input:
                if isinstance(item, str):
                    target_urls.append(item)
        elif isinstance(raw_input, str):
            clean_str = raw_input.strip()
            # Check if passed as a JSON array string e.g. '["https://..."]'
            if clean_str.startswith("[") and clean_str.endswith("]"):
                try:
                    parsed = json.loads(clean_str)
                    if isinstance(parsed, list):
                        target_urls.extend([str(x) for x in parsed if x])
                except Exception:
                    pass

            # If still empty or not parsed, extract using regex
            if not target_urls:
                found = re.findall(r'https?://[^\s"\'\]\)\<\>]+', clean_str)
                if found:
                    target_urls.extend(found)
                elif clean_str:
                    target_urls.append(clean_str)

        # Sanitize and normalize URLs
        cleaned_urls = []
        for u in target_urls:
            u_clean = u.strip().strip("[]'\"<>() \t\r\n")
            if u_clean.startswith("http://") or u_clean.startswith("https://"):
                cleaned_urls.append(u_clean)
            elif u_clean and "." in u_clean:
                cleaned_urls.append("https://" + u_clean)

        if not cleaned_urls:
            return "Error: No valid HTTP or HTTPS URLs provided to extract."

        output = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8"
        }

        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True, verify=False) as client:
            for target in cleaned_urls[:3]:
                try:
                    resp = await client.get(target)
                    if resp.status_code != 200:
                        output.append(f"URL: {target}\nStatus: HTTP {resp.status_code} (Failed to load page)")
                        continue

                    html_content = resp.text
                    # Strip scripts, styles, svg, and HTML comments
                    cleaned = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r'<svg[^>]*>.*?</svg>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r'<nav[^>]*>.*?</nav>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r'<footer[^>]*>.*?</footer>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
                    cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)

                    # Strip HTML tags
                    text = re.sub(r'<[^>]+>', ' ', cleaned)
                    # Clean whitespace
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    clean_text = "\n".join(lines)

                    if len(clean_text) > 4500:
                        clean_text = clean_text[:4500] + "\n...[Content truncated for length]"

                    if not clean_text:
                        clean_text = "[No readable text content extracted from this URL]"

                    output.append(f"URL: {target}\nExtracted Content:\n{clean_text}")
                except Exception as ex:
                    output.append(f"URL: {target}\nError loading page: {str(ex)}")

        return "\n\n---\n\n".join(output)

    return [
        Tool(
            name="web_search",
            description="Perform a real-time web search for information, documentation, news, or technical facts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query string"},
                    "max_results": {"type": "integer", "description": "Maximum number of results (default 5)", "default": 5}
                },
                "required": ["query"]
            },
            handler=web_search
        ),
        Tool(
            name="web_extract",
            description="Fetch a URL (or list of URLs) and extract readable text content from articles, docs, or web reports.",
            parameters={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to fetch and extract content from"
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional single URL to fetch and extract content from"
                    }
                }
            },
            handler=web_extract
        )
    ]
