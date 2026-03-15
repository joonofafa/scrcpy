"""FastAPI routes — all /api/* and /auth/* endpoints."""

import base64
import io
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from scrcpy_ai.agent.agent import agent
from scrcpy_ai.auth import (
    create_session,
    get_or_create_secret,
    get_provisioning_uri,
    verify_otp,
)
from scrcpy_ai.clip.matcher import embed_image_bytes
from scrcpy_ai.config import config
from scrcpy_ai.pipeline import recorder

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_safe_session_name(name: str) -> bool:
    """Validate session name to block traversal and invalid paths."""
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    return os.path.basename(name) == name


# ── Auth ───────────────────────────────────────────────────────────
@router.post("/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    code = body.get("code", "")
    if not verify_otp(code):
        return JSONResponse({"ok": False, "error": "인증 실패"}, status_code=401)
    token = create_session()
    response = JSONResponse({"ok": True})
    # Apache proxies HTTPS→HTTP internally, so check X-Forwarded-Proto
    is_https = request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=15 * 60,
    )
    return response


@router.get("/auth/setup")
async def auth_setup(request: Request):
    """QR code setup — internal access only."""
    from scrcpy_ai.auth import is_internal_request

    client_host = request.client.host if request.client else ""
    forwarded_for = request.headers.get("x-forwarded-for")
    host_header = request.headers.get("host")
    if not is_internal_request(client_host, forwarded_for, host_header):
        raise HTTPException(403, "internal access only")

    import qrcode

    uri = get_provisioning_uri()
    secret = get_or_create_secret()

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {"qr_base64": qr_b64, "secret": secret}


# ── State ───────────────────────────────────────────────────────────
@router.get("/api/state")
async def get_state():
    return agent.get_state()


# ── Prompt ──────────────────────────────────────────────────────────
@router.post("/api/prompt")
async def post_prompt(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(400, "missing prompt")
    import threading
    threading.Thread(target=agent.process_prompt, args=(prompt,), daemon=True).start()
    return {"ok": True}


# ── Config ──────────────────────────────────────────────────────────
@router.post("/api/config")
async def post_config(request: Request):
    body = await request.json()
    if body.get("api_key"):
        config.api_key = body["api_key"]
    if body.get("model"):
        config.model = body["model"]
    if body.get("base_url"):
        config.base_url = body["base_url"]
    if body.get("vision_model"):
        config.vision_model = body["vision_model"]
    return {"ok": True}


# ── Game Rules ──────────────────────────────────────────────────────
@router.get("/api/game-rules")
async def get_game_rules():
    return {"rules": agent.game_rules}


@router.post("/api/game-rules")
async def post_game_rules(request: Request):
    body = await request.json()
    agent.game_rules = body.get("rules", "")
    return {"ok": True}


# ── Auto Play ───────────────────────────────────────────────────────
@router.post("/api/auto/start")
async def auto_start():
    agent.start_auto()
    return {"ok": True}


@router.post("/api/auto/stop")
async def auto_stop():
    agent.stop_auto()
    return {"ok": True}


# ── History ─────────────────────────────────────────────────────────
@router.post("/api/clear")
async def clear_history():
    agent.clear_history()
    return {"ok": True}


# ── Recording ───────────────────────────────────────────────────────
@router.post("/api/record/start")
async def record_start():
    agent.recording = True
    agent.record_count = 0
    try:
        # Allocate a dedicated session directory immediately, so it is listed
        # even when later captures fail.
        agent._record_session_dir = recorder.get_session_dir()
        return {"ok": True, "session": os.path.basename(agent._record_session_dir)}
    except OSError as e:
        agent.recording = False
        agent._record_session_dir = None
        logger.exception("Failed to create recording session directory")
        raise HTTPException(500, f"failed to create session directory: {e}") from e


@router.post("/api/record/stop")
async def record_stop():
    agent.recording = False
    return {"ok": True}


@router.post("/api/record/capture")
async def record_capture(request: Request):
    """Save a video frame (from browser) + touch coordinates during recording."""
    if not agent.recording:
        return {"ok": False, "reason": "not recording"}

    form = await request.form()
    frame = form.get("frame")
    try:
        x = int(form.get("x", 0))
        y = int(form.get("y", 0))
        index = int(form.get("index", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid x, y, or index")
    if index <= 0 or not frame:
        raise HTTPException(400, "missing index or frame")
    if x < 0 or y < 0:
        raise HTTPException(400, "invalid touch coordinates")

    # Get or create session directory (one per recording session)
    if not hasattr(agent, '_record_session_dir') or not agent._record_session_dir:
        try:
            agent._record_session_dir = recorder.get_session_dir()
        except OSError as e:
            logger.exception("Failed to lazily create recording session directory")
            raise HTTPException(500, f"failed to create session directory: {e}") from e

    jpeg_bytes = await frame.read()
    if not jpeg_bytes:
        raise HTTPException(400, "empty frame payload")
    # Defensive bound against abusive uploads.
    if len(jpeg_bytes) > 12 * 1024 * 1024:
        raise HTTPException(413, "frame payload too large")
    try:
        recorder.save_capture(agent._record_session_dir, index, jpeg_bytes, x, y)
    except OSError as e:
        logger.exception(
            "Failed to save capture (session=%s index=%d size=%d)",
            agent._record_session_dir, index, len(jpeg_bytes),
        )
        return JSONResponse(
            {"ok": False, "reason": f"save failed: {e}"},
            status_code=500,
        )
    agent.record_count = index
    return {"ok": True, "index": index}


@router.post("/api/record/clear")
async def record_clear():
    agent.recording = False
    agent.record_count = 0
    agent._record_session_dir = None
    return {"ok": True}


# ── Train Sessions ──────────────────────────────────────────────────
@router.get("/api/train/sessions")
async def train_sessions():
    return recorder.list_sessions()


@router.get("/api/train/session")
async def train_session(name: str):
    if not _is_safe_session_name(name):
        raise HTTPException(400, "invalid session name")
    return recorder.get_session(name)


@router.post("/api/train/session/delete")
async def train_session_delete(request: Request):
    body = await request.json()
    name = body.get("name", "")
    if not name:
        raise HTTPException(400, "missing name")
    if recorder.delete_session(name):
        return {"ok": True}
    raise HTTPException(404, "session not found")


# ── Train Images ────────────────────────────────────────────────────
@router.get("/api/train/image")
async def train_image(session: str, index: int):
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session name")
    path = os.path.join(config.record_dir, session, f"{index:04d}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "image not found")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


# ── Train Embed ─────────────────────────────────────────────────────
@router.post("/api/train/embed")
async def train_embed(request: Request):
    body = await request.json()
    session = body.get("session", "")
    index = body.get("index", 0)
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session")
    try:
        index_int = int(index)
    except (TypeError, ValueError):
        raise HTTPException(400, "invalid index")
    if index_int <= 0:
        raise HTTPException(400, "missing session or index")

    # Read image file
    img_path = os.path.join(config.record_dir, session, f"{index_int:04d}.jpg")
    if not os.path.exists(img_path):
        raise HTTPException(404, "image not found")

    with open(img_path, "rb") as f:
        jpeg_bytes = f.read()

    emb = embed_image_bytes(jpeg_bytes)
    if emb is None:
        raise HTTPException(500, "embedding failed")

    # Load existing embeddings or create new
    embeddings = recorder.load_embeddings(session) or []

    # Read touch coordinates
    txt_path = os.path.join(config.record_dir, session, f"{index_int:04d}.txt")
    x, y = 0, 0
    if os.path.exists(txt_path):
        try:
            with open(txt_path) as f:
                parts = f.read().strip().split(",")
            x, y = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            pass

    # Update or append
    found = False
    for e in embeddings:
        if e.get("index") == index_int:
            e["embedding"] = emb.tolist()
            e["x"] = x
            e["y"] = y
            found = True
            break
    if not found:
        embeddings.append({
            "index": index_int,
            "x": x,
            "y": y,
            "embedding": emb.tolist(),
        })

    recorder.save_embeddings(session, embeddings)
    return {"ok": True}


@router.get("/api/train/embeddings")
async def train_embeddings(session: str):
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session")
    data = recorder.load_embeddings(session)
    return data or []


# ── CLIP Load/Clear ─────────────────────────────────────────────────
@router.post("/api/clip/load")
async def clip_load(request: Request):
    body = await request.json()
    session = body.get("session", "")
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session")
    data = recorder.load_embeddings(session)
    if not data:
        raise HTTPException(404, "no embeddings found")
    agent.clip_embeddings = data
    return {"ok": True, "count": len(data)}


@router.post("/api/clip/clear")
async def clip_clear():
    agent.clip_embeddings = None
    return {"ok": True}


# ── Hybrid Mode ────────────────────────────────────────────────────
@router.post("/api/hybrid/toggle")
async def hybrid_toggle(request: Request):
    body = await request.json()
    agent.hybrid_enabled = body.get("enabled", True)
    return {"ok": True, "hybrid_enabled": agent.hybrid_enabled}


@router.get("/api/memory/stats")
async def memory_stats():
    from scrcpy_ai.db.memory_manager import memory
    return memory.stats()


@router.post("/api/memory/clear-history")
async def memory_clear_history():
    agent.action_history.clear()
    agent._prev_phash = None
    agent._same_screen_count = 0
    return {"ok": True}


# ── Train Labels ────────────────────────────────────────────────────
@router.get("/api/train/labels")
async def train_labels(session: str):
    import json
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session")
    labels_path = os.path.join(config.record_dir, session, "labels.json")
    if not os.path.exists(labels_path):
        return {"ok": True}
    try:
        with open(labels_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"ok": True}


# ── Train Save (Confirm) ────────────────────────────────────────────
@router.post("/api/train/save")
async def train_save(request: Request):
    body = await request.json()
    session = body.get("session")
    labels = body.get("labels", {})
    if not _is_safe_session_name(session):
        raise HTTPException(400, "invalid session")
    if not isinstance(labels, dict):
        raise HTTPException(400, "invalid labels")

    # Save labels to labels.json in session directory
    import json
    labels_path = os.path.join(config.record_dir, session, "labels.json")
    with open(labels_path, "w") as f:
        json.dump(labels, f)
    return {"ok": True}


# ── Train Tree ──────────────────────────────────────────────────────
@router.get("/api/train/tree")
async def get_tree():
    return agent.train_tree or {"states": []}


@router.post("/api/train/tree")
async def post_tree(request: Request):
    body = await request.json()
    agent.train_tree = body
    return {"ok": True}
