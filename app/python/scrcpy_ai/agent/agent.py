"""Core AI agent: manages conversation, LLM loop, tool execution."""

import json
import logging
import threading
import time

from scrcpy_ai.config import config
from scrcpy_ai.device import client as device
from scrcpy_ai.device.tool_executor import execute as execute_tool
from scrcpy_ai.device.tools import TOOL_DEFINITIONS
from scrcpy_ai.llm.openrouter import analyze_screen, chat_completion

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI assistant controlling an Android device via scrcpy.\n\n"
    "*** FUNCTION CALLING IS MANDATORY ***\n"
    "You have tools: position_click, position_long_press, swipe, "
    "key_press, input_text, screenshot.\n"
    "You MUST use function calling (tool_calls) to invoke them.\n"
    "NEVER output JSON in text. NEVER write code blocks with actions.\n"
    "ALWAYS use the tool_calls mechanism provided by the API.\n\n"
    "SCREEN COORDINATES:\n"
    "- Screenshot caption shows 'Screenshot WxH' = actual pixel dimensions.\n"
    "- Valid range: X: 0..W-1, Y: 0..H-1. (0,0) = top-left.\n"
    "- ONLY use cx/cy values from VLM analysis. NEVER guess.\n\n"
    "ACTION PROTOCOL:\n"
    "1. State which element you will tap and WHY (brief).\n"
    "2. Call the tool via function calling.\n"
    "3. Call screenshot() to verify the result.\n"
    "4. If screen unchanged -> tap MISSED -> try different element.\n\n"
    "AUTONOMOUS MODE:\n"
    "- Follow game rules step by step. NEVER ask the user.\n"
    "- Every response MUST include at least one tool call.\n"
    "- If unsure, call screenshot() first, then act on what you see."
)

MAX_MESSAGES = 40
MAX_ITERATIONS = 50


class AIAgent:
    def __init__(self):
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.activity_log: list[dict] = []  # {role, content} for UI display
        self.lock = threading.Lock()

        # State
        self.auto_running = False
        self.recording = False
        self.record_count = 0
        self.game_rules = ""
        self.screen_width = 0
        self.screen_height = 0

        # CLIP
        self.clip_embeddings: list[dict] | None = None

        # Train tree
        self.train_tree: dict | None = None

        # Auto-play thread
        self._auto_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _log(self, role: str, content: str):
        """Add to activity log (shown in web UI)."""
        with self.lock:
            self.activity_log.append({"role": role, "content": content})
            # Keep log bounded
            if len(self.activity_log) > 200:
                self.activity_log = self.activity_log[-200:]

    def _trim_messages(self):
        """Keep message history bounded."""
        if len(self.messages) <= MAX_MESSAGES:
            return
        # Keep system prompt + last N messages
        keep = MAX_MESSAGES - 1
        # Skip orphaned tool messages
        start = len(self.messages) - keep
        while start < len(self.messages) and self.messages[start].get("role") == "tool":
            start -= 1
        if start < 1:
            start = 1
        self.messages = [self.messages[0]] + self.messages[start:]

    def clear_history(self):
        with self.lock:
            self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            self.activity_log = []

    def _take_screenshot_with_vlm(self) -> str | None:
        """Capture screenshot, analyze with VLM, add to messages. Returns VLM description."""
        ss = device.screenshot()
        if not ss:
            return None

        self.screen_width = ss.screenshot_w
        self.screen_height = ss.screenshot_h

        # VLM analysis
        description = None
        if config.vision_model:
            description = analyze_screen(ss.base64_data, ss.screenshot_w, ss.screenshot_h)

        # Build message
        if description:
            text = (
                f"Screenshot {ss.screenshot_w}x{ss.screenshot_h} (fresh)\n"
                f"=== VLM ANALYSIS (use these EXACT coordinates) ===\n"
                f"{description}\n"
                f"=== END VLM ANALYSIS ==="
            )
            self.messages.append({"role": "user", "content": text})
        else:
            text = f"Screenshot {ss.screenshot_w}x{ss.screenshot_h} (fresh)"
            self.messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{ss.base64_data}",
                    }},
                ],
            })

        return description

    def process_prompt(self, prompt: str):
        """Process a user prompt through the LLM loop."""
        # Add user message
        self.messages.append({"role": "user", "content": prompt})
        self._log("user", prompt)

        consecutive_text = 0
        for iteration in range(MAX_ITERATIONS):
            if self._stop_event.is_set():
                logger.info("Agent stopped during process_prompt")
                break

            logger.info("LLM call iteration %d (auto=%s)", iteration, self.auto_running)

            self._trim_messages()

            # Call LLM
            result = chat_completion(self.messages, TOOL_DEFINITIONS)

            if "error" in result:
                self._log("assistant", f"[Error] {result['error']}")
                break

            content = result.get("content")
            tool_calls = result.get("tool_calls")

            if tool_calls:
                consecutive_text = 0

                # Add assistant message with tool calls
                assistant_msg = {"role": "assistant", "tool_calls": tool_calls}
                if content:
                    assistant_msg["content"] = content
                    self._log("assistant", content)
                self.messages.append(assistant_msg)

                # Execute each tool call
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    # Screenshot is special - needs VLM
                    if fn_name == "screenshot":
                        desc = self._take_screenshot_with_vlm()
                        tool_result = json.dumps({
                            "success": True,
                            "width": self.screen_width,
                            "height": self.screen_height,
                        })
                        self._log("assistant", f"[Screenshot] {self.screen_width}x{self.screen_height}")
                    else:
                        result_dict = execute_tool(fn_name, args)
                        tool_result = json.dumps(result_dict)
                        self._log("assistant", f"[Tool] {fn_name}({json.dumps(args)}) -> {tool_result[:200]}")

                    # Add tool result message
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })

                continue  # loop back to get next LLM response

            # Text-only response (no tool calls)
            if content:
                self._log("assistant", content)
                self.messages.append({"role": "assistant", "content": content})

            # In auto mode with CLIP loaded: don't auto-continue (CLIP has its own loop)
            if self.clip_embeddings:
                break

            # In auto mode: continue with fresh screenshot
            if self.auto_running and not self._stop_event.is_set():
                consecutive_text += 1
                if consecutive_text >= 3:
                    logger.warning("3 consecutive text-only responses, stopping loop")
                    break
                time.sleep(0.5)
                self._take_screenshot_with_vlm()
                continue

            break  # manual mode: done

    def start_auto(self):
        """Start auto-play loop."""
        if self.auto_running:
            return
        self.auto_running = True
        self._stop_event.clear()
        self.activity_log = []
        self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self._auto_thread.start()

    def stop_auto(self):
        """Stop auto-play loop."""
        self.auto_running = False
        self._stop_event.set()

    def _auto_loop(self):
        """Main auto-play loop. Runs in background thread."""
        logger.info("Auto-play started")
        rules_sent = False

        while not self._stop_event.is_set():
            # Priority: CLIP > Tree > Rules
            if self.clip_embeddings:
                self._clip_auto_cycle()
                if self._stop_event.wait(2.0):
                    break
                continue

            if self.train_tree and self.train_tree.get("states"):
                self._tree_auto_cycle()
                if self._stop_event.wait(2.0):
                    break
                continue

            # Rules mode (LLM-based)
            if self.game_rules:
                if not rules_sent:
                    prompt = (
                        "Follow the game rules below, look at the screenshot, "
                        "and use the available tools to play.\n\n"
                        + self.game_rules
                    )
                    rules_sent = True
                else:
                    prompt = "Take a screenshot and continue playing."
                self.process_prompt(prompt)
            else:
                # Nothing to do
                if self._stop_event.wait(1.0):
                    break
                continue

            if self._stop_event.wait(1.0):
                break

        self.auto_running = False
        logger.info("Auto-play stopped")

    def _clip_auto_cycle(self):
        """One cycle of CLIP-based auto-play."""
        from scrcpy_ai.clip.matcher import clip_auto_cycle
        clip_auto_cycle(self)

    def _tree_auto_cycle(self):
        """One cycle of tree-based auto-play."""
        # Placeholder - will be implemented in pipeline/player.py
        self._log("assistant", "[Tree] Tree-based play not yet implemented in Python")
        time.sleep(5)

    def get_play_mode(self) -> str:
        if self.clip_embeddings:
            return "clip"
        if self.train_tree and self.train_tree.get("states"):
            return "tree"
        if self.game_rules:
            return "rules"
        return "none"

    def get_state(self) -> dict:
        """Build state dict for web UI polling."""
        with self.lock:
            messages_for_ui = []
            for m in self.messages:
                role = m.get("role", "")
                content = m.get("content", "")
                # Filter base64 images from content
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            parts.append("[Screenshot]")
                        elif isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                    content = "\n".join(parts)
                msg = {"role": role, "content": content or ""}
                tc = m.get("tool_calls")
                if tc:
                    msg["tool_calls"] = json.dumps(tc)
                messages_for_ui.append(msg)

            return {
                "screen_width": self.screen_width,
                "screen_height": self.screen_height,
                "messages": messages_for_ui,
                "auto_running": self.auto_running,
                "recording": self.recording,
                "record_count": self.record_count,
                "game_rules": self.game_rules,
                "play_mode": self.get_play_mode(),
                "clip_count": len(self.clip_embeddings) if self.clip_embeddings else 0,
                "config_api_key": "sk-****" if len(config.api_key) > 8 else config.api_key,
                "config_model": config.model,
                "config_vision_model": config.vision_model,
                "config_base_url": config.base_url,
            }


# Global agent instance
agent = AIAgent()
