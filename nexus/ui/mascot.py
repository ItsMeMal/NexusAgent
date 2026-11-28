"""
nexus/ui/mascot.py
Animated True-Color Half-Block Pixel Sprite & Terminal Graphics (Kitty / iTerm2 / Sixel)
engine for the Nolthira Mascot (Piko).
"""

from __future__ import annotations

import base64
import os
import struct
import zlib
from typing import Dict, List, Optional, Tuple

from rich.table import Table
from rich.text import Text


# ---------------------------------------------------------------------------
# Terminal Graphics Protocol Detection (Option 2: Kitty / iTerm2 / Sixel)
# ---------------------------------------------------------------------------

def detect_graphics_protocol(override: Optional[str] = None) -> str:
    """
    Detect active terminal rendering mode:
    'pixel' (True-Color half-block RGB — universal fallback),
    or native graphics protocol 'kitty' | 'iterm2' | 'sixel' when explicitly enabled/supported.
    """
    pref = (override or os.getenv("NEXUS_MASCOT_MODE", "auto")).strip().lower()
    if pref in ("pixel", "kitty", "iterm2", "sixel"):
        return pref

    # Auto mode: detect native graphics terminals (keep 'pixel' default inside standard WT/PowerShell/SSH
    # so Rich Live transient updates remain flicker-free across all consoles)
    term_prog = (os.getenv("TERM_PROGRAM") or "").lower()
    term = (os.getenv("TERM") or "").lower()
    if os.getenv("KITTY_WINDOW_ID") or "kitty" in term or term_prog == "ghostty":
        return "kitty"
    if term_prog in ("iterm.app", "wezterm") or os.getenv("WEZTERM_EXECUTABLE"):
        return "iterm2"
    if os.getenv("NEXUS_ENABLE_SIXEL", "").lower() in ("1", "true", "yes"):
        return "sixel"
    return "pixel"


# ---------------------------------------------------------------------------
# Color Palettes & Procedural 18x8 Pixel Sprite Frames (4 terminal lines)
# ---------------------------------------------------------------------------

# Dynamic multi-color palettes shifting smoothly over time
_THEME_PALETTES = {
    "think": [
        # (highlight, upper, mid, lower, shadow, blush, foot, spark_a, spark_b)
        ("#b8fff4", "#00ffd7", "#38bdf8", "#818cf8", "#4f46e5", "#ff5c93", "#c084fc", "#fbbf24", "#f472b6"),
        ("#d8f3ff", "#22d3ee", "#60a5fa", "#a78bfa", "#6d28d9", "#fb7185", "#f472b6", "#00ffd7", "#fbbf24"),
        ("#fde7ff", "#38bdf8", "#a78bfa", "#e879f9", "#9333ea", "#ff4d8d", "#38bdf8", "#f472b6", "#00ffd7"),
    ],
    "tool": [
        ("#fef08a", "#fbbf24", "#fb923c", "#f472b6", "#be185d", "#ff477e", "#38bdf8", "#00ffd7", "#fde047"),
        ("#fed7aa", "#f59e0b", "#f43f5e", "#c084fc", "#7e22ce", "#ff6b9d", "#00ffd7", "#fbbf24", "#f472b6"),
    ],
    "synth": [
        ("#f3e8ff", "#c084fc", "#e879f9", "#38bdf8", "#4f46e5", "#ff5c93", "#00ffd7", "#fbbf24", "#67e8f9"),
    ],
    "cozy": [
        # Used when wait > 20s so long runs evolve visually instead of looping monotonously
        ("#fef9c3", "#f472b6", "#c084fc", "#38bdf8", "#4338ca", "#ff4d8d", "#fbbf24", "#00ffd7", "#fde047"),
    ],
}

# 18x8 sprite blueprints. '.' = transparent
# Characters: H=highlight, A=upper, B=mid, C=lower, S=shadow, E=eye, W=eye_glint,
#             P=pink_blush, M=mouth, F=foot, Y=spark_a, K=spark_b

_POSE_IDLE_CENTER = [
    "..Y...HHHHHH...K..",
    "....HHAAAAAAHH....",
    "...HAAWEAAEWAAH...",
    "...AAAEAAAAEAAA...",
    "..KPPAAAMMAAAPP...",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    ".....FF....FF.....",
]

_POSE_LOOK_RIGHT = [
    "...K..HHHHHH....Y.",
    "....HHAAAAAAHH....",
    "...HAAAWEAAWEAH...",
    "...AAAAEAAAAEAA...",
    "...PPAAAAMMAAAPP..",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    ".....FF....FF.....",
]

_POSE_LOOK_LEFT = [
    ".Y....HHHHHH..K...",
    "....HHAAAAAAHH....",
    "...HEWAAEWAAAAH...",
    "...AEAAAAEAAAAA...",
    "..PPAAAMMAAAAPP...",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    ".....FF....FF.....",
]

_POSE_HAPPY_BLINK = [
    ".Y..K.HHHHHH.K..Y.",
    "....HHAAAAAAHH....",
    "...HAAEEAAEEAAH...",
    "...AAAPAAAAPAAA...",
    "..PPPAAAMMMAAAPPP.",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    "....FF......FF....",
]

_POSE_JUMP_HIGH = [
    "....HHHHHHHHHH....",
    "..HHAAAAAAAAAAHH..",
    "..AAWWEAAAAEWWAA..",
    "..AAEAAAMMMAAEAA..",
    ".KPPPCCCCCCCCPPPY.",
    "...SSCCCCCCCCSS...",
    "....FF......FF....",
    "..................",
]

_POSE_SQUISH_LAND = [
    "..................",
    ".Y..............K.",
    "..HHHHHHHHHHHHHH..",
    ".HAAWEAAAAAAEWAAH.",
    ".BAAEAAAMMMAAEAAAB",
    ".CPPCCCCCCCCCCPPPC",
    "..SSSCCCCCCCCSSS..",
    "...FFF......FFF...",
]

_POSE_WALK_RIGHT = [
    "...Y...HHHHHH.....",
    ".....HHAAAAAAHH...",
    "....HAAWEAAEWAAH..",
    "....AAAEAAAAEAAA..",
    "....PPAAAMMAAAPPK.",
    "....BBBCCCCCCBBB..",
    ".....SSCCCCCCSS...",
    "......FF..FF......",
]

_POSE_WALK_LEFT = [
    ".....HHHHHH...K...",
    "...HHAAAAAAHH.....",
    "..HAAWEAAEWAAH....",
    "..AAAEAAAAEAAA....",
    ".YPPAAAMMAAAPP....",
    "..BBBCCCCCCBBB....",
    "...SSCCCCCCSS.....",
    ".....FF..FF.......",
]

_POSE_TOOL_WORK_A = [
    ".Y..K.HHHHHH.Y..K.",
    "....HHAAAAAAHH....",
    "...HAAWEAAEWAAH...",
    "...AAAEAAAAEAAA...",
    "..YPPAAAMMAAAPPK..",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    "....FF......FF....",
]

_POSE_TOOL_WORK_B = [
    "K....HHHHHHHH....Y",
    "....HHAAAAAAHH....",
    "...HAAEEAAEEAAH...",
    "...AAAWWAAWWAAA...",
    "..KPPAAAAMMAAAPPY.",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    ".....FF....FF.....",
]

_POSE_COZY_WAIT = [
    "....K.HHHHHH..Y...",
    "....HHAAAAAAHH....",
    "...HAAEEAAEEAAH...",
    "...AAAPAAAAPAAA...",
    "...PPAAAMMMAAAPP..",
    "...BBBCCCCCCBBB...",
    "....SSCCCCCCSS....",
    ".....FF....FF.....",
]

# Multi-phase choreography sequences (rich & non-repetitive)
_THINK_SEQUENCE = [
    _POSE_IDLE_CENTER, _POSE_IDLE_CENTER,
    _POSE_LOOK_RIGHT, _POSE_LOOK_RIGHT,
    _POSE_IDLE_CENTER,
    _POSE_HAPPY_BLINK,
    _POSE_LOOK_LEFT, _POSE_LOOK_LEFT,
    _POSE_WALK_RIGHT, _POSE_JUMP_HIGH, _POSE_SQUISH_LAND,
    _POSE_WALK_LEFT, _POSE_IDLE_CENTER,
    _POSE_HAPPY_BLINK, _POSE_JUMP_HIGH, _POSE_SQUISH_LAND,
]

_TOOL_SEQUENCE = [
    _POSE_TOOL_WORK_A, _POSE_TOOL_WORK_B,
    _POSE_WALK_RIGHT, _POSE_TOOL_WORK_A,
    _POSE_JUMP_HIGH, _POSE_SQUISH_LAND,
    _POSE_WALK_LEFT, _POSE_TOOL_WORK_B,
]

_COZY_SEQUENCE = [
    _POSE_COZY_WAIT, _POSE_COZY_WAIT,
    _POSE_LOOK_RIGHT, _POSE_HAPPY_BLINK,
    _POSE_JUMP_HIGH, _POSE_SQUISH_LAND,
    _POSE_LOOK_LEFT, _POSE_COZY_WAIT,
]


def _select_pose_and_palette(frame_idx: int, elapsed: float, mode_kind: str) -> Tuple[List[str], Dict[str, Optional[str]]]:
    # Duration-reactive evolution so long runs (>20s) switch choreography smoothly
    if mode_kind == "tool":
        seq = _COZY_SEQUENCE if elapsed >= 25.0 and (frame_idx // 12) % 3 == 2 else _TOOL_SEQUENCE
        pal_list = _THEME_PALETTES["tool"]
    elif mode_kind == "synth":
        seq = _THINK_SEQUENCE
        pal_list = _THEME_PALETTES["synth"]
    elif elapsed >= 20.0:
        seq = _COZY_SEQUENCE
        pal_list = _THEME_PALETTES["cozy"]
    else:
        seq = _THINK_SEQUENCE
        pal_list = _THEME_PALETTES["think"]

    pose = seq[frame_idx % len(seq)]
    pal_tuple = pal_list[(frame_idx // 4) % len(pal_list)]
    hl, up, mid, low, sh, blush, foot, sp_a, sp_b = pal_tuple
    cmap: Dict[str, Optional[str]] = {
        ".": None,
        "H": hl,
        "A": up,
        "B": mid,
        "C": low,
        "S": sh,
        "E": "#0f172a",
        "W": "#ffffff",
        "P": blush,
        "M": "#f43f5e",
        "F": foot,
        "Y": sp_a if (frame_idx % 2 == 0) else sp_b,
        "K": sp_b if (frame_idx % 2 == 0) else sp_a,
    }
    return pose, cmap


# ---------------------------------------------------------------------------
# Option 1 Renderer: True-Color Half-Block Pixel Art (▀ ▄ █)
# ---------------------------------------------------------------------------

def render_pixel_sprite_text(frame_idx: int, elapsed: float, mode_kind: str) -> Text:
    """Render an 18x8 pixel sprite cleanly as 4 lines of Rich True-Color half-blocks."""
    pose, cmap = _select_pose_and_palette(frame_idx, elapsed, mode_kind)
    width = len(pose[0])
    out = Text()

    for row_pair in range(0, len(pose), 2):
        top_row = pose[row_pair]
        bot_row = pose[row_pair + 1] if row_pair + 1 < len(pose) else ("." * width)
        for col in range(width):
            tc = cmap.get(top_row[col])
            bc = cmap.get(bot_row[col])
            if tc is None and bc is None:
                out.append(" ")
            elif tc is not None and bc is None:
                out.append("▀", style=tc)
            elif tc is None and bc is not None:
                out.append("▄", style=bc)
            elif tc == bc:
                out.append("█", style=tc)
            else:
                out.append("▀", style=f"{tc} on {bc}")
        if row_pair + 2 < len(pose):
            out.append("\n")
    return out


# ---------------------------------------------------------------------------
# Option 2 Encoders: PNG + Kitty / iTerm2 / Sixel Graphics Protocols
# ---------------------------------------------------------------------------

def _hex_to_rgba(hex_c: Optional[str]) -> Tuple[int, int, int, int]:
    if not hex_c:
        return (0, 0, 0, 0)
    h = hex_c.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def render_mascot_png_bytes(frame_idx: int, elapsed: float = 0.0, mode_kind: str = "think", scale: int = 4) -> bytes:
    """Pure-Python RGBA PNG encoder for the Piko pixel sprite (used by Kitty / iTerm2 protocols)."""
    pose, cmap = _select_pose_and_palette(frame_idx, elapsed, mode_kind)
    w_src, h_src = len(pose[0]), len(pose)
    w, h = w_src * scale, h_src * scale

    raw_rows = bytearray()
    for py in range(h):
        raw_rows.append(0)  # PNG filter type 0
        src_row = pose[py // scale]
        for px in range(w):
            r, g, b, a = _hex_to_rgba(cmap.get(src_row[px // scale]))
            raw_rows.extend((r, g, b, a))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(bytes(raw_rows), level=6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def encode_kitty_image(png_bytes: bytes) -> str:
    """Encode PNG bytes using the Kitty Terminal Graphics Protocol."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)]
    seq = []
    for idx, ch in enumerate(chunks):
        more = 1 if idx < len(chunks) - 1 else 0
        if idx == 0:
            seq.append(f"\x1b_Ga=T,f=100,q=2,m={more};{ch}\x1b\\")
        else:
            seq.append(f"\x1b_Gm={more};{ch}\x1b\\")
    return "".join(seq)


def encode_iterm2_image(png_bytes: bytes) -> str:
    """Encode PNG bytes using iTerm2 / WezTerm inline image OSC 1337 sequence."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"\x1b]1337;File=inline=1;width=8;height=4;preserveAspectRatio=1:{b64}\x07"


def encode_sixel_image(frame_idx: int, elapsed: float = 0.0, mode_kind: str = "think", scale: int = 3) -> str:
    """Encode the Piko pixel sprite directly as a compact DEC Sixel graphics sequence."""
    pose, cmap = _select_pose_and_palette(frame_idx, elapsed, mode_kind)
    w_src, h_src = len(pose[0]), len(pose)
    w, h = w_src * scale, h_src * scale

    palette_list: List[str] = []
    color_idx: Dict[str, int] = {}
    for row in pose:
        for ch in row:
            hx = cmap.get(ch)
            if hx and hx not in color_idx:
                idx = len(palette_list) + 1
                color_idx[hx] = idx
                palette_list.append(hx)

    parts = ["\x1bPq"]
    for idx, hx in enumerate(palette_list, 1):
        r, g, b, _ = _hex_to_rgba(hx)
        parts.append(f"#{idx};2;{round(r * 100 / 255)};{round(g * 100 / 255)};{round(b * 100 / 255)}")

    for band_y in range(0, h, 6):
        first_in_band = True
        for c_hx, c_id in color_idx.items():
            band_chars = []
            has_any = False
            for x in range(w):
                bits = 0
                for dy in range(6):
                    py = band_y + dy
                    if py < h:
                        px_char = pose[py // scale][x // scale]
                        if cmap.get(px_char) == c_hx:
                            bits |= (1 << dy)
                if bits:
                    has_any = True
                band_chars.append(chr(63 + bits))
            if has_any:
                if not first_in_band:
                    parts.append("$")
                parts.append(f"#{c_id}" + "".join(band_chars))
                first_in_band = False
        parts.append("-")

    parts.append("\x1b\\")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Unified Mascot + Telemetry Widget Builder
# ---------------------------------------------------------------------------

_SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_PULSE_PALETTE = ["#00ffd7", "#38bdf8", "#818cf8", "#c084fc", "#f472b6", "#fb7185", "#fbbf24"]


def build_piko_renderable(
    frame_idx: int,
    elapsed: float,
    message: str = "Thinking & coordinating...",
    model_name: str = "",
    width: int = 100,
    mode_id: str = "auto",
    protocol_override: Optional[str] = None,
):
    """Build the unified multi-color Pixel Sprite + live telemetry grid for Rich Live."""
    msg_low = (message or "").lower()
    if msg_low.startswith("executing") or "tool" in msg_low:
        mode_kind = "tool"
        badge_text = " EXECUTING "
        badge_style = "bold #11111b on #f59e0b"
    elif "synth" in msg_low:
        mode_kind = "synth"
        badge_text = " SYNTHESIZING "
        badge_style = "bold #11111b on #c084fc"
    elif "retry" in msg_low:
        mode_kind = "tool"
        badge_text = " RETRYING "
        badge_style = "bold #11111b on #fb7185"
    else:
        mode_kind = "think"
        badge_text = " THINKING "
        badge_style = "bold #11111b on #00ffd7"

    spin = _SPINNERS[frame_idx % len(_SPINNERS)]
    proto = detect_graphics_protocol(protocol_override)

    # Compact 1-line fallback for ultra-narrow panes
    if width < 64:
        t = Text()
        t.append("  ")
        t.append("●", style="bold #00ffd7")
        t.append("◡", style="bold #f472b6")
        t.append("●", style="bold #38bdf8")
        t.append(f" {spin} {message[:26]} ", style="bold #38bdf8")
        t.append(f"({elapsed:.1f}s)", style="dim")
        return t

    # Render mascot sprite (True-color pixel sprite always renders cleanly inside Rich Live;
    # native protocol image string can also be accessed via encode_* helpers when invoked directly)
    mascot = render_pixel_sprite_text(frame_idx, elapsed, mode_kind)

    model_short = (model_name.split("/")[-1] if "/" in model_name else model_name) or "nolthira"
    if len(model_short) > 28:
        model_short = model_short[:25] + "..."

    bar_len = 24
    cycle = bar_len * 2 - 2
    pos = frame_idx % cycle
    if pos >= bar_len:
        pos = cycle - pos

    from ..core.modes import get_mode
    mode_spec = get_mode(mode_id)

    info = Text()
    info.append("◈ NOLTHIRA ", style="bold #00ffd7")
    info.append("PIKO ", style="bold #f472b6")
    info.append(badge_text, style=badge_style)
    info.append(f"  {mode_spec.icon} {mode_spec.label}", style=f"bold {mode_spec.color}")
    info.append(f"  ·  {model_short}\n", style="dim #94a3b8")

    clean_msg = message if len(message) <= 44 else message[:41] + "..."
    info.append(f"{spin} ", style=f"bold {_PULSE_PALETTE[frame_idx % len(_PULSE_PALETTE)]}")
    info.append(f"{clean_msg}\n", style="bold white")

    info.append("[", style="dim #475569")
    for i in range(bar_len):
        dist = abs(i - pos)
        if dist == 0:
            info.append("✦", style="bold #ffffff")
        elif dist <= 2:
            info.append("━", style=f"bold {_PULSE_PALETTE[(i + frame_idx) % len(_PULSE_PALETTE)]}")
        elif dist <= 5:
            info.append("━", style=_PULSE_PALETTE[(i + frame_idx) % len(_PULSE_PALETTE)])
        else:
            info.append("─", style="#334155")
    info.append("]\n", style="dim #475569")

    info.append(f"◷ {elapsed:4.1f}s", style="bold #38bdf8")
    if proto != "pixel":
        info.append(f" · {proto}", style="dim #a78bfa")
    info.append("  ·  ", style="dim")
    info.append("Esc / Ctrl+C to interrupt", style="dim #94a3b8")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_row(mascot, info)
    return grid
