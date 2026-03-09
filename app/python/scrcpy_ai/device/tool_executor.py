"""Execute tool calls by dispatching to device client."""

import json
import logging

from scrcpy_ai.device import client

logger = logging.getLogger(__name__)


def execute(function_name: str, arguments: dict) -> dict:
    """Execute a tool and return the result dict."""
    logger.info("Tool: %s(%s)", function_name, json.dumps(arguments, ensure_ascii=False))

    if function_name == "position_click":
        return client.click(
            arguments["x"], arguments["y"],
            arguments.get("w", 0), arguments.get("h", 0),
        )
    elif function_name == "position_long_press":
        return client.long_press(
            arguments["x"], arguments["y"],
            arguments.get("duration_ms", 500),
        )
    elif function_name == "swipe":
        return client.swipe(
            arguments["x1"], arguments["y1"],
            arguments["x2"], arguments["y2"],
            arguments.get("duration_ms", 300),
        )
    elif function_name == "key_press":
        return client.key_press(arguments["keycode"])
    elif function_name == "key_down":
        return client.key_down(arguments["keycode"])
    elif function_name == "key_up":
        return client.key_up(arguments["keycode"])
    elif function_name == "input_text":
        return client.input_text(arguments["text"])
    elif function_name == "screenshot":
        # Screenshot is handled specially by the agent (needs VLM analysis)
        return {"_screenshot_requested": True}
    else:
        return {"error": f"unknown tool: {function_name}"}
