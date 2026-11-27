"""
nexus/tools/media.py
Multimodal output tools: image_generate and text_to_speech (TTS).
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import httpx

from ..config import config
from .base import Tool


def get_media_tools(root_dir: Path, api_key: str = "", api_base: str = "") -> List[Tool]:
    def _resolve_out(output_path: str, default_prefix: str, ext: str) -> Path:
        if output_path and output_path.strip():
            p = Path(output_path.strip())
            out = p if p.is_absolute() else (root_dir / p).resolve()
        else:
            config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            out = config.SCREENSHOTS_DIR / f"{default_prefix}_{int(time.time())}.{ext}"
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    async def image_generate(
        prompt: str,
        output_path: str = "",
        size: str = "1024x1024",
        model: str = "",
    ) -> str:
        """Generate an image via OpenAI-compatible /images/generations endpoint and save to disk."""
        if not prompt or not prompt.strip():
            return "Error: 'prompt' is required."
        base = (api_base or config.API_BASE).rstrip("/")
        key = api_key or config.API_KEY
        img_model = model or os.getenv("NEXUS_IMAGE_MODEL", "dall-e-3")
        url = f"{base}/images/generations"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        payload = {"model": img_model, "prompt": prompt.strip(), "size": size, "n": 1}

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    return f"Image generation API error ({resp.status_code}): {resp.text[:300]}"
                data = resp.json()
                item = (data.get("data") or [{}])[0]
                out = _resolve_out(output_path, "generated", "png")
                if item.get("b64_json"):
                    out.write_bytes(base64.b64decode(item["b64_json"]))
                    return f"Successfully generated image saved to '{out}'."
                if item.get("url"):
                    img_resp = await client.get(item["url"])
                    if img_resp.status_code == 200:
                        out.write_bytes(img_resp.content)
                        return f"Successfully generated image saved to '{out}' (from {item['url']})."
                    return f"Generated image URL: {item['url']}"
                return f"Unexpected response format from /images/generations: {str(data)[:200]}"
        except Exception as exc:
            return f"Error generating image: {exc}"

    async def text_to_speech(
        text: str,
        output_path: str = "",
        voice: str = "alloy",
        model: str = "",
    ) -> str:
        """Convert text to speech audio (.mp3/.wav) via API /audio/speech with offline OS fallback."""
        if not text or not text.strip():
            return "Error: 'text' cannot be empty."
        base = (api_base or config.API_BASE).rstrip("/")
        key = api_key or config.API_KEY
        tts_model = model or os.getenv("NEXUS_TTS_MODEL", "tts-1")
        out = _resolve_out(output_path, "speech", "mp3")

        # 1. Try OpenAI-compatible /audio/speech endpoint
        if key and key != "your_api_key_here":
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{base}/audio/speech",
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                        json={"model": tts_model, "input": text.strip(), "voice": voice},
                    )
                    if resp.status_code == 200 and len(resp.content) > 100:
                        out.write_bytes(resp.content)
                        return f"Successfully generated TTS audio saved to '{out}'."
            except Exception:
                pass

        # 2. Offline OS speech synthesizer fallback
        wav_out = out.with_suffix(".wav")
        try:
            if sys.platform == "win32":
                safe_txt = text.strip().replace("'", "''")[:800]
                ps = (
                    f"Add-Type -AssemblyName System.Speech; "
                    f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.SetOutputToWaveFile('{str(wav_out)}'); "
                    f"$s.Speak('{safe_txt}'); $s.Dispose()"
                )
                proc = await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-Command", ps,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=20.0)
                if wav_out.exists() and wav_out.stat().st_size > 0:
                    return f"Successfully synthesized offline TTS audio saved to '{wav_out}'."
            elif sys.platform == "darwin":
                proc = await asyncio.create_subprocess_exec("say", "-o", str(wav_out), "--data-format=LEI16@22050", text.strip()[:800])
                await asyncio.wait_for(proc.communicate(), timeout=20.0)
                if wav_out.exists():
                    return f"Successfully synthesized TTS audio saved to '{wav_out}'."
            else:
                proc = await asyncio.create_subprocess_exec("espeak", "-w", str(wav_out), text.strip()[:800])
                await asyncio.wait_for(proc.communicate(), timeout=20.0)
                if wav_out.exists():
                    return f"Successfully synthesized TTS audio saved to '{wav_out}'."
        except Exception as exc:
            return f"TTS unavailable (API failed & OS fallback error: {exc})."

        return "TTS generation did not produce audio output (provider /audio/speech returned unsupported)."

    return [
        Tool(
            name="image_generate",
            description="Generate an image from a text prompt via /images/generations and save it locally.",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed visual prompt for image generation"},
                    "output_path": {"type": "string", "description": "Optional output file path (e.g. 'assets/hero.png')", "default": ""},
                    "size": {"type": "string", "description": "Image dimensions (e.g. '1024x1024')", "default": "1024x1024"},
                    "model": {"type": "string", "description": "Optional image model override", "default": ""},
                },
                "required": ["prompt"],
            },
            handler=image_generate,
        ),
        Tool(
            name="text_to_speech",
            description="Convert text to spoken audio file (.mp3/.wav) via /audio/speech with offline OS fallback.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to synthesize into speech"},
                    "output_path": {"type": "string", "description": "Optional output path", "default": ""},
                    "voice": {"type": "string", "description": "Voice ID (e.g. 'alloy', 'nova', 'echo')", "default": "alloy"},
                    "model": {"type": "string", "description": "Optional TTS model override", "default": ""},
                },
                "required": ["text"],
            },
            handler=text_to_speech,
        ),
    ]
