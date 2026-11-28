"""
nexus/tools/browser.py
Native Chromium/Playwright browser automation tool with clean HTTP fallback.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import config
from .base import Tool


class _BrowserSessionManager:
    """Manages a lazy Playwright Chromium instance across turns."""

    def __init__(self, screenshots_dir: Path):
        self.screenshots_dir = screenshots_dir
        self._pw = None
        self._browser = None
        self._page = None
        self._last_url = ""

    async def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install playwright && playwright install chromium` "
                "or use `web_extract` for static pages."
            ) from exc

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        context = await self._browser.new_context(viewport={"width": 1280, "height": 800})
        self._page = await context.new_page()
        return self._page

    async def open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            page = await self._ensure_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            self._last_url = page.url
            title = await page.title()
            return f"Opened '{title}' ({page.url}). Use action='snapshot' to read interactive elements."
        except RuntimeError as no_pw:
            # Lightweight HTTP fallback if Playwright is unavailable
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    self._last_url = str(resp.url)
                    title_m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S)
                    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else str(resp.url)
                    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.I | re.S)
                    clean = re.sub(r"<[^>]+>", " ", clean)
                    clean = re.sub(r"\s+", " ", clean).strip()[:1600]
                    return f"[HTTP Fallback — {no_pw}]\nTitle: {title}\nURL: {resp.url}\n\n{clean}"
            except Exception as exc:
                return f"Browser error: {exc}"
        except Exception as exc:
            return f"Browser navigation error: {exc}"

    async def snapshot(self) -> str:
        try:
            page = await self._ensure_page()
            data = await page.evaluate(
                """() => {
                    const text = (document.body?.innerText || '').trim().slice(0, 2500);
                    const links = Array.from(document.querySelectorAll('a, button, input, select, textarea'))
                        .slice(0, 35)
                        .map((el, i) => {
                            const tag = el.tagName.toLowerCase();
                            const id = el.id ? '#' + el.id : '';
                            const lbl = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '').trim().slice(0, 45);
                            const href = tag === 'a' ? (el.getAttribute('href') || '') : '';
                            return `${i+1}. <${tag}${id}> ${lbl}${href ? ' -> ' + href.slice(0,60) : ''}`;
                        });
                    return { url: location.href, title: document.title, text, links };
                }"""
            )
            links_txt = "\n".join(data.get("links", [])) or "(none)"
            return (
                f"Page: {data.get('title')} ({data.get('url')})\n\n"
                f"--- Interactive Elements ---\n{links_txt}\n\n"
                f"--- Visible Text ---\n{data.get('text', '')}"
            )
        except Exception as exc:
            return f"Snapshot error: {exc}"

    async def click(self, selector: str) -> str:
        try:
            page = await self._ensure_page()
            try:
                await page.click(selector, timeout=8000)
            except Exception:
                await page.get_by_text(selector, exact=False).first.click(timeout=8000)
            self._last_url = page.url
            return f"Clicked '{selector}'. Current URL: {page.url}"
        except Exception as exc:
            return f"Click error on '{selector}': {exc}"

    async def type_text(self, selector: str, text: str) -> str:
        try:
            page = await self._ensure_page()
            await page.fill(selector, text, timeout=8000)
            return f"Typed {len(text)} chars into '{selector}'."
        except Exception as exc:
            return f"Type error on '{selector}': {exc}"

    async def evaluate(self, script: str) -> str:
        try:
            page = await self._ensure_page()
            res = await page.evaluate(script)
            return f"Eval result: {res}"
        except Exception as exc:
            return f"Eval error: {exc}"

    async def screenshot(self, path: str = "") -> str:
        try:
            page = await self._ensure_page()
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            out = Path(path) if path else (self.screenshots_dir / f"browser_{int(time.time())}.png")
            await page.screenshot(path=str(out), full_page=False)
            return f"Browser screenshot saved to '{out}'."
        except Exception as exc:
            return f"Screenshot error: {exc}"

    async def close(self) -> str:
        try:
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._browser = None
        self._pw = None
        return "Browser session closed."


def get_browser_tools(root_dir: Optional[Path] = None) -> List[Tool]:
    mgr = _BrowserSessionManager(config.SCREENSHOTS_DIR)

    async def browser(
        action: str,
        url: str = "",
        selector: str = "",
        text: str = "",
        script: str = "",
        path: str = "",
    ) -> str:
        """Control a built-in headless Chromium browser (open, snapshot, click, type, eval, screenshot, close)."""
        act = (action or "").strip().lower()
        if act in ("open", "goto", "navigate"):
            if not url:
                return "Error: 'url' is required for action='open'."
            return await mgr.open_url(url)
        if act == "snapshot":
            return await mgr.snapshot()
        if act == "click":
            if not selector:
                return "Error: 'selector' is required for action='click'."
            return await mgr.click(selector)
        if act in ("type", "fill"):
            if not selector:
                return "Error: 'selector' is required for action='type'."
            return await mgr.type_text(selector, text)
        if act in ("eval", "js"):
            if not script:
                return "Error: 'script' is required for action='eval'."
            return await mgr.evaluate(script)
        if act == "screenshot":
            target_path = path
            if target_path and root_dir and not Path(target_path).is_absolute():
                target_path = str((root_dir / target_path).resolve())
            return await mgr.screenshot(target_path)
        if act == "close":
            return await mgr.close()
        return f"Unknown browser action '{action}'. Use: open, snapshot, click, type, eval, screenshot, close."

    return [
        Tool(
            name="browser",
            description=(
                "Built-in headless Chromium browser automation (Playwright). Actions: "
                "open (url), snapshot, click (selector or text), type (selector, text), "
                "eval (script), screenshot (path), close."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "snapshot", "click", "type", "eval", "screenshot", "close"],
                    },
                    "url": {"type": "string", "description": "URL for action='open'"},
                    "selector": {"type": "string", "description": "CSS selector or visible label for click/type"},
                    "text": {"type": "string", "description": "Text to type for action='type'"},
                    "script": {"type": "string", "description": "JavaScript expression for action='eval'"},
                    "path": {"type": "string", "description": "Optional output PNG path for screenshot"},
                },
                "required": ["action"],
            },
            handler=browser,
        )
    ]
