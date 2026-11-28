import os
import sys
import time
import base64
import mimetypes
import platform
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from .base import Tool
from ..config import Config

# Optional PyAutoGUI import with safe fallbacks
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_PYAUTOGUI = True
except Exception:
    pyautogui = None
    HAS_PYAUTOGUI = False

# Optional MSS import
try:
    import mss
    HAS_MSS = True
except Exception:
    mss = None
    HAS_MSS = False

# Optional PIL import
try:
    from PIL import Image, ImageGrab
    HAS_PIL = True
except Exception:
    Image = None
    ImageGrab = None
    HAS_PIL = False

# Optional Pyperclip import for unicode text typing
try:
    import pyperclip
    HAS_PYPERCLIP = True
except Exception:
    pyperclip = None
    HAS_PYPERCLIP = False


def _capture_screen_fallback(output_path: Path) -> Dict[str, Any]:
    """Capture screen using available OS-level tools or PIL/MSS."""
    # 1. Try PyAutoGUI
    if HAS_PYAUTOGUI:
        try:
            img = pyautogui.screenshot()
            img.save(str(output_path))
            return {"width": img.width, "height": img.height}
        except Exception:
            pass

    # 2. Try MSS
    if HAS_MSS:
        try:
            with mss.MSS() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(output_path))
                return {"width": sct_img.width, "height": sct_img.height}
        except Exception:
            pass

    # 3. Try PIL ImageGrab
    if HAS_PIL and ImageGrab:
        try:
            img = ImageGrab.grab()
            img.save(str(output_path))
            return {"width": img.width, "height": img.height}
        except Exception:
            pass

    # 4. OS CLI fallbacks
    sys_plat = platform.system().lower()
    if sys_plat == "darwin":
        # macOS screencapture
        res = subprocess.run(["screencapture", "-x", str(output_path)], capture_output=True)
        if res.returncode == 0 and output_path.exists():
            return {"width": 0, "height": 0}
    elif sys_plat == "linux":
        # Linux scrot or import
        for cmd in [["scrot", str(output_path)], ["import", "-window", "root", str(output_path)]]:
            try:
                res = subprocess.run(cmd, capture_output=True)
                if res.returncode == 0 and output_path.exists():
                    return {"width": 0, "height": 0}
            except FileNotFoundError:
                continue

    raise RuntimeError(
        "Could not capture screenshot. No active display server or screenshot utility found. "
        "Ensure an active graphical desktop session is running."
    )


def get_computer_tools(llm_client: Optional[Any] = None) -> List[Tool]:
    """Factory creating the unified 'computer' GUI automation tool."""

    async def computer(
        action: str,
        coordinate: Optional[List[int]] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        keys: Optional[List[str]] = None,
        amount: Optional[int] = None,
        prompt: Optional[str] = None
    ) -> str:
        """Perform GUI automation actions on the computer (screenshot, click, move, type, hotkey, scroll, launch)."""
        act = action.strip().lower()

        # ----------------------------------------------------
        # 1. SCREENSHOT
        # ----------------------------------------------------
        if act == "screenshot":
            screenshots_dir = Config.SCREENSHOTS_DIR
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            filename = f"screen_{int(time.time())}.png"
            target_path = screenshots_dir / filename

            try:
                info = _capture_screen_fallback(target_path)
                dim_str = f"{info['width']}x{info['height']}" if info.get("width") else "Native"
                result_msg = f"Screenshot successfully captured: {target_path} (Resolution: {dim_str})"

                # If LLM client is available and prompt is supplied, visually analyze immediately
                if llm_client and prompt:
                    mime = "image/png"
                    b64_data = base64.b64encode(target_path.read_bytes()).decode("utf-8")
                    data_url = f"data:{mime};base64,{b64_data}"
                    
                    vision_messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"Computer Screen Analysis: {prompt}"},
                                {"type": "image_url", "image_url": {"url": data_url}}
                            ]
                        }
                    ]
                    analysis_resp = await llm_client.chat_completion(messages=vision_messages)
                    analysis_text = analysis_resp.get("content", "No analysis returned.")
                    return f"{result_msg}\n\nVisual Screen Analysis:\n{analysis_text}"

                return f"{result_msg}\n(Use view_image or computer(action='screenshot', prompt='...') to analyze details)"
            except Exception as e:
                return f"Error taking screenshot: {str(e)}"

        # ----------------------------------------------------
        # 2. CURSOR POSITION & RESOLUTION
        # ----------------------------------------------------
        if act in ("cursor_position", "screen_size"):
            if not HAS_PYAUTOGUI:
                return "Error: PyAutoGUI is required for cursor telemetry. Run: pip install pyautogui"
            try:
                w, h = pyautogui.size()
                x, y = pyautogui.position()
                return f"Screen Resolution: {w}x{h} | Current Mouse Position: ({x}, {y})"
            except Exception as e:
                return f"Error reading cursor position: {str(e)}"

        # ----------------------------------------------------
        # 3. MOUSE ACTIONS (move, click, drag, scroll)
        # ----------------------------------------------------
        if act in ("mouse_move", "left_click", "right_click", "double_click", "triple_click", "middle_click", "drag", "mouse_down", "mouse_up"):
            if not HAS_PYAUTOGUI:
                return f"Error: PyAutoGUI is required for mouse automation '{act}'. Run: pip install pyautogui"

            try:
                x, y = None, None
                if coordinate and len(coordinate) >= 2:
                    x, y = int(coordinate[0]), int(coordinate[1])

                if act == "mouse_move":
                    if x is None or y is None:
                        return "Error: 'coordinate' parameter [x, y] is required for 'mouse_move'."
                    pyautogui.moveTo(x, y, duration=0.15)
                    return f"Moved cursor to ({x}, {y})."

                elif act == "left_click":
                    if x is not None and y is not None:
                        pyautogui.click(x, y, button="left")
                        return f"Left-clicked at ({x}, {y})."
                    pyautogui.click(button="left")
                    return "Left-clicked at current cursor position."

                elif act == "right_click":
                    if x is not None and y is not None:
                        pyautogui.click(x, y, button="right")
                        return f"Right-clicked at ({x}, {y})."
                    pyautogui.click(button="right")
                    return "Right-clicked at current cursor position."

                elif act == "double_click":
                    if x is not None and y is not None:
                        pyautogui.doubleClick(x, y)
                        return f"Double-clicked at ({x}, {y})."
                    pyautogui.doubleClick()
                    return "Double-clicked at current cursor position."

                elif act == "triple_click":
                    if x is not None and y is not None:
                        pyautogui.tripleClick(x, y)
                        return f"Triple-clicked at ({x}, {y})."
                    pyautogui.tripleClick()
                    return "Triple-clicked at current cursor position."

                elif act == "middle_click":
                    if x is not None and y is not None:
                        pyautogui.middleClick(x, y)
                        return f"Middle-clicked at ({x}, {y})."
                    pyautogui.middleClick()
                    return "Middle-clicked at current cursor position."

                elif act == "drag":
                    if x is None or y is None:
                        return "Error: Destination 'coordinate' [x, y] is required for 'drag'."
                    pyautogui.dragTo(x, y, duration=0.4, button="left")
                    return f"Dragged mouse cursor to ({x}, {y})."

                elif act == "mouse_down":
                    pyautogui.mouseDown(button="left")
                    return "Pressed down left mouse button."

                elif act == "mouse_up":
                    pyautogui.mouseUp(button="left")
                    return "Released left mouse button."

            except Exception as e:
                return f"Error executing mouse action '{act}': {str(e)}"

        # ----------------------------------------------------
        # 4. SCROLL
        # ----------------------------------------------------
        if act == "scroll":
            if not HAS_PYAUTOGUI:
                return "Error: PyAutoGUI is required for scrolling. Run: pip install pyautogui"
            scroll_amount = amount if amount is not None else -3
            try:
                pyautogui.scroll(scroll_amount * 120)
                direction = "up" if scroll_amount > 0 else "down"
                return f"Scrolled {direction} by {abs(scroll_amount)} units."
            except Exception as e:
                return f"Error scrolling: {str(e)}"

        # ----------------------------------------------------
        # 5. KEYBOARD ACTIONS (type, key, hotkey)
        # ----------------------------------------------------
        if act == "type":
            if not text:
                return "Error: 'text' parameter is required for 'type' action."
            if not HAS_PYAUTOGUI:
                return "Error: PyAutoGUI is required for typing. Run: pip install pyautogui"

            try:
                # Use clipboard pasting if text contains non-ascii characters (unicode, emoji, etc.)
                is_ascii = all(ord(c) < 128 for c in text)
                if not is_ascii and HAS_PYPERCLIP:
                    pyperclip.copy(text)
                    paste_key = "command" if sys.platform == "darwin" else "ctrl"
                    pyautogui.hotkey(paste_key, "v")
                    time.sleep(0.05)
                else:
                    pyautogui.write(text, interval=0.01)
                return f"Successfully typed {len(text)} characters."
            except Exception as e:
                return f"Error typing text: {str(e)}"

        if act == "key":
            if not key:
                return "Error: 'key' parameter (e.g. 'enter', 'tab', 'escape', 'space') is required."
            if not HAS_PYAUTOGUI:
                return "Error: PyAutoGUI is required to press keys. Run: pip install pyautogui"

            key_map = {
                "return": "enter",
                "esc": "escape",
                "del": "delete",
                "ins": "insert"
            }
            target_key = key_map.get(key.lower(), key.lower())
            try:
                pyautogui.press(target_key)
                return f"Pressed key '{target_key}'."
            except Exception as e:
                return f"Error pressing key '{key}': {str(e)}"

        if act == "hotkey":
            key_combo = keys
            if not key_combo and key:
                key_combo = [k.strip() for k in key.split("+")]
            if not key_combo:
                return "Error: 'keys' parameter (e.g. ['ctrl', 'c'] or ['alt', 'tab']) is required for 'hotkey'."
            if not HAS_PYAUTOGUI:
                return "Error: PyAutoGUI is required to trigger hotkeys. Run: pip install pyautogui"

            # Normalize keys
            norm_keys = []
            for k in key_combo:
                kl = k.lower()
                if kl in ("win", "windows", "super", "cmd", "command"):
                    norm_keys.append("command" if sys.platform == "darwin" else "win")
                elif kl in ("control", "ctl"):
                    norm_keys.append("ctrl")
                elif kl in ("return",):
                    norm_keys.append("enter")
                else:
                    norm_keys.append(kl)

            try:
                pyautogui.hotkey(*norm_keys)
                return f"Pressed hotkey: {' + '.join(norm_keys)}."
            except Exception as e:
                return f"Error pressing hotkey '{key_combo}': {str(e)}"

        # ----------------------------------------------------
        # 6. APP LAUNCH / RUN GUI APP
        # ----------------------------------------------------
        if act in ("app_launch", "open_app"):
            if not text:
                return "Error: 'text' parameter (application name or URL) is required for 'app_launch'."
            target = text.strip()

            # Prevent dangerous commands through app launch
            blocked_prefixes = ["rm ", "del ", "format ", "dd ", "mkfs"]
            if any(target.lower().startswith(b) for b in blocked_prefixes):
                return f"Security Error: Command '{target}' is blocked from GUI application launcher."

            try:
                if sys.platform == "win32":
                    subprocess.Popen(target, shell=True)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", target])
                else:
                    subprocess.Popen(["xdg-open", target] if "://" in target else [target], shell=False)
                return f"Launched application / URI: {target}"
            except Exception as e:
                return f"Error launching application '{target}': {str(e)}"

        return f"Unknown computer action: '{action}'. Available actions: screenshot, mouse_move, left_click, right_click, double_click, triple_click, middle_click, drag, mouse_down, mouse_up, type, key, hotkey, scroll, cursor_position, app_launch."

    return [
        Tool(
            name="computer",
            description="Control and automate the computer GUI: capture screenshots with optional vision analysis, move the mouse cursor, click buttons, drag, scroll, type text, trigger keyboard hotkeys, and launch desktop applications.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "screenshot",
                            "mouse_move",
                            "left_click",
                            "right_click",
                            "double_click",
                            "triple_click",
                            "middle_click",
                            "drag",
                            "mouse_down",
                            "mouse_up",
                            "type",
                            "key",
                            "hotkey",
                            "scroll",
                            "cursor_position",
                            "app_launch"
                        ],
                        "description": "The GUI automation action to perform."
                    },
                    "coordinate": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "(x, y) screen pixel coordinates for mouse actions, e.g. [500, 300]."
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type for 'type' action, or application/URL to execute for 'app_launch'."
                    },
                    "key": {
                        "type": "string",
                        "description": "Single key name to press for 'key' action (e.g. 'enter', 'tab', 'escape', 'backspace', 'up', 'down')."
                    },
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key sequence for 'hotkey' action, e.g. ['ctrl', 'c'], ['alt', 'tab'], ['win', 'r']."
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Scroll delta units (positive for up, negative for down)."
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional vision question when action='screenshot' (e.g. 'Locate the login button coordinates', 'What window is open?')."
                    }
                },
                "required": ["action"]
            },
            handler=computer
        )
    ]
