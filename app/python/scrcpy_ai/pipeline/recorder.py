"""Recording sessions: capture screenshots + touch coordinates."""

import json
import logging
import os
import time

from scrcpy_ai.config import config
from scrcpy_ai.device import client as device

logger = logging.getLogger(__name__)


def _is_safe_session_name(name: str) -> bool:
    """Validate session name to prevent path traversal."""
    if not name:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    return os.path.basename(name) == name


def get_session_dir() -> str:
    """Get or create the current recording session directory."""
    os.makedirs(config.record_dir, exist_ok=True)
    # Use milliseconds + fallback suffix to avoid same-second collisions.
    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = int((time.time() % 1) * 1000)
    base_name = f"{ts}_{ms:03d}"
    path = os.path.join(config.record_dir, base_name)

    if not os.path.exists(path):
        os.makedirs(path)
        return path

    for i in range(1, 1000):
        candidate = os.path.join(config.record_dir, f"{base_name}_{i:03d}")
        if not os.path.exists(candidate):
            os.makedirs(candidate)
            return candidate

    raise RuntimeError("failed to allocate unique session directory")


def list_sessions() -> list[dict]:
    """List all recording sessions."""
    sessions = []
    base = config.record_dir
    if not os.path.isdir(base):
        return sessions
    try:
        names = sorted(os.listdir(base), reverse=True)
    except OSError as e:
        logger.warning("Failed to list record base directory %s: %s", base, e)
        return sessions

    for name in names:
        if not _is_safe_session_name(name):
            continue
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        # Count captures; skip unreadable/broken directories.
        try:
            count = len([f for f in os.listdir(path) if f.endswith(".jpg")])
        except OSError as e:
            logger.warning("Skipping unreadable session directory %s: %s", path, e)
            continue
        sessions.append({"name": name, "count": count})
    return sessions


def get_session(name: str) -> list[dict]:
    """Get captures for a session."""
    if not _is_safe_session_name(name):
        return []
    path = os.path.join(config.record_dir, name)
    if not os.path.isdir(path):
        return []

    captures = []
    try:
        files = os.listdir(path)
    except OSError as e:
        logger.warning("Failed to list session directory %s: %s", path, e)
        return []

    for fname in files:
        if not fname.endswith(".jpg"):
            continue
        try:
            idx = int(fname.replace(".jpg", ""))
        except ValueError:
            continue
        txt = os.path.join(path, f"{idx:04d}.txt")
        x, y = 0, 0
        if os.path.exists(txt):
            try:
                data = open(txt).read().strip()
                parts = data.split(",")
                if len(parts) >= 2:
                    x, y = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                pass
        captures.append({"index": idx, "x": x, "y": y})

    captures.sort(key=lambda c: c["index"])
    return captures


def delete_session(name: str) -> bool:
    """Delete a recording session."""
    import shutil
    if not _is_safe_session_name(name):
        return False
    path = os.path.join(config.record_dir, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return True
    return False


def save_capture(session_dir: str, index: int, jpeg_bytes: bytes, x: int, y: int):
    """Save a capture (screenshot + touch coords) to session directory."""
    jpg_path = os.path.join(session_dir, f"{index:04d}.jpg")
    txt_path = os.path.join(session_dir, f"{index:04d}.txt")
    with open(jpg_path, "wb") as f:
        f.write(jpeg_bytes)
    with open(txt_path, "w") as f:
        f.write(f"{x},{y}")


def load_embeddings(session_name: str) -> list[dict] | None:
    """Load embeddings.json from a session directory."""
    if not _is_safe_session_name(session_name):
        return None
    path = os.path.join(config.record_dir, session_name, "embeddings.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_embeddings(session_name: str, embeddings: list[dict]):
    """Save embeddings.json to a session directory."""
    if not _is_safe_session_name(session_name):
        raise ValueError("invalid session name")
    path = os.path.join(config.record_dir, session_name, "embeddings.json")
    with open(path, "w") as f:
        json.dump(embeddings, f)
