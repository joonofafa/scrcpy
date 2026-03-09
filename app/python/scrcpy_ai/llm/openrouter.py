"""LLM and VLM calls via OpenAI-compatible API (OpenRouter)."""

import logging

from openai import OpenAI

from scrcpy_ai.config import config

logger = logging.getLogger(__name__)

_llm_client: OpenAI | None = None
_vlm_client: OpenAI | None = None


def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None or _llm_client.api_key != config.api_key:
        _llm_client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
    return _llm_client


def _get_vlm_client() -> OpenAI:
    global _vlm_client
    if _vlm_client is None or _vlm_client.api_key != config.api_key:
        _vlm_client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
    return _vlm_client


def chat_completion(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Call LLM with messages and optional tools. Returns parsed response."""
    try:
        client = _get_llm_client()
        kwargs = {
            "model": config.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        result = {
            "content": choice.message.content,
            "tool_calls": None,
        }

        if choice.message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]

        return result

    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return {"error": str(e)}


def analyze_screen(base64_jpeg: str, width: int, height: int) -> str | None:
    """Analyze screenshot with VLM. Returns screen description with coordinates."""
    if not config.vision_model:
        return None

    prompt = (
        f"Analyze this Android screenshot ({width}x{height}). "
        "List EVERY visible UI element with PRECISE bounding box: "
        "element_description cx=X cy=Y w=W h=H [type]. "
        "Types: [button], [text], [icon], [card], [input]. "
        "Start with: SCREEN: one-line description. Then ELEMENTS: list."
    )

    try:
        client = _get_vlm_client()
        response = client.chat.completions.create(
            model=config.vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_jpeg}",
                        },
                    },
                ],
            }],
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("VLM call failed: %s", e)
        return None
