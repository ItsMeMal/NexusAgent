import base64
import mimetypes
from pathlib import Path
from typing import Optional, List
from .base import Tool
from ..core.llm import LLMClient

def get_vision_tools(llm_client: LLMClient, root_dir: Path) -> List[Tool]:
    async def view_image(image_path: str, prompt: str = "Analyze and describe this image in detail.") -> str:
        """Inspect a local image file or screenshot, extracting text (OCR), UI elements, diagrams, or visual bugs."""
        path = Path(image_path)
        if not path.is_absolute():
            path = (root_dir / path).resolve()

        if not path.exists():
            return f"Error: Image file '{image_path}' not found at {path}."

        mime, _ = mimetypes.guess_type(str(path))
        if not mime or not mime.startswith("image/"):
            return f"Error: File '{path.name}' is not recognized as a supported image format."

        try:
            image_bytes = path.read_bytes()
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:{mime};base64,{b64_data}"

            # Query vision-capable LLM
            vision_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Analyze this image according to: {prompt}"},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ]

            resp = await llm_client.chat_completion(messages=vision_messages)
            analysis = resp.get("content", "No visual analysis returned.")
            return f"Image Analysis for '{path.name}':\n{analysis}"
        except Exception as e:
            return f"Error analyzing image: {str(e)}"

    return [
        Tool(
            name="view_image",
            description="Inspect, read text from, or visually analyze a local image file, screenshot, diagram, or UI mockup using multimodal vision.",
            parameters={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Path to the local image file (e.g. 'screenshot.png', 'assets/logo.png', 'ui.jpg')"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Specific question or visual details to examine (e.g. 'Read the error in this screenshot', 'Extract form fields')",
                        "default": "Analyze and describe this image in detail."
                    }
                },
                "required": ["image_path"]
            },
            handler=view_image
        )
    ]
