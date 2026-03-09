"""Tool definitions for OpenAI function calling format."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "position_click",
            "description": "Tap at a specific screen position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate (center of target)"},
                    "y": {"type": "integer", "description": "Y coordinate (center of target)"},
                    "w": {"type": "integer", "description": "Bounding box width (optional)"},
                    "h": {"type": "integer", "description": "Bounding box height (optional)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "position_long_press",
            "description": "Long press at a specific screen position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "duration_ms": {"type": "integer", "description": "Hold duration in ms", "default": 500},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swipe",
            "description": "Swipe from one position to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "integer", "description": "Start X"},
                    "y1": {"type": "integer", "description": "Start Y"},
                    "x2": {"type": "integer", "description": "End X"},
                    "y2": {"type": "integer", "description": "End Y"},
                    "duration_ms": {"type": "integer", "description": "Duration in ms", "default": 300},
                },
                "required": ["x1", "y1", "x2", "y2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "key_press",
            "description": "Press an Android key (4=BACK, 3=HOME, 24=VOL_UP, 25=VOL_DOWN, 26=POWER, 66=ENTER).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keycode": {"type": "integer", "description": "Android keycode"},
                },
                "required": ["keycode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "input_text",
            "description": "Type text string on the device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a fresh screenshot. Use after actions to verify results.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]
