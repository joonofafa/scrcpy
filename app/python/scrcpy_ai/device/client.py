"""Thin HTTP client for scrcpy C internal API."""

import base64
import logging

import httpx

from scrcpy_ai.config import config

logger = logging.getLogger(__name__)

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=config.scrcpy_url, timeout=10.0)
    return _client


def close():
    global _client
    if _client:
        _client.close()
        _client = None


class ScreenshotResult:
    def __init__(self, jpeg_bytes: bytes, base64_data: str,
                 screenshot_w: int, screenshot_h: int,
                 frame_w: int, frame_h: int):
        self.jpeg_bytes = jpeg_bytes
        self.base64_data = base64_data
        self.screenshot_w = screenshot_w
        self.screenshot_h = screenshot_h
        self.frame_w = frame_w
        self.frame_h = frame_h


def screenshot() -> ScreenshotResult | None:
    """Capture a screenshot from scrcpy. Returns JPEG bytes + dimensions."""
    try:
        r = get_client().get("/internal/screenshot")
        if r.status_code != 200:
            logger.error("Screenshot failed: %d %s", r.status_code, r.text)
            return None
        sw = int(r.headers.get("X-Screenshot-Width", 0))
        sh = int(r.headers.get("X-Screenshot-Height", 0))
        fw = int(r.headers.get("X-Frame-Width", 0))
        fh = int(r.headers.get("X-Frame-Height", 0))
        jpeg = r.content
        b64 = base64.b64encode(jpeg).decode("ascii")
        return ScreenshotResult(jpeg, b64, sw, sh, fw, fh)
    except httpx.HTTPError as e:
        logger.error("Screenshot request failed: %s", e)
        return None


def click(x: int, y: int, w: int = 0, h: int = 0) -> dict:
    """Tap at screen coordinates."""
    try:
        r = get_client().post("/internal/click",
                              json={"x": x, "y": y, "w": w, "h": h})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def long_press(x: int, y: int, duration_ms: int = 500) -> dict:
    """Long press at screen coordinates."""
    try:
        r = get_client().post("/internal/long_press",
                              json={"x": x, "y": y, "duration_ms": duration_ms})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict:
    """Swipe from (x1,y1) to (x2,y2)."""
    try:
        r = get_client().post("/internal/swipe",
                              json={"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                    "duration_ms": duration_ms})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def key_press(keycode: int) -> dict:
    try:
        r = get_client().post("/internal/key",
                              json={"keycode": keycode, "action": "press"})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def key_down(keycode: int) -> dict:
    try:
        r = get_client().post("/internal/key",
                              json={"keycode": keycode, "action": "down"})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def key_up(keycode: int) -> dict:
    try:
        r = get_client().post("/internal/key",
                              json={"keycode": keycode, "action": "up"})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def input_text(text: str) -> dict:
    try:
        r = get_client().post("/internal/text", json={"text": text})
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def info() -> dict:
    """Get device info (frame dimensions, etc.)."""
    try:
        r = get_client().get("/internal/info")
        return r.json()
    except Exception as e:
        return {"error": str(e)}
