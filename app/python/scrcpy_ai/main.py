"""FastAPI application entry point."""

import argparse
import asyncio
import logging
import os

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from scrcpy_ai.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="scrcpy-ai", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def startup():
    logger.info("scrcpy-ai starting on port %d", config.web_port)
    logger.info("scrcpy backend: %s", config.scrcpy_url)


@app.on_event("shutdown")
async def shutdown():
    from scrcpy_ai.device import client
    client.close()


# WebSocket proxy: relay /ws/video and /ws/control to C backend
async def _ws_proxy(client_ws: WebSocket, path: str):
    backend_url = f"ws://{config.scrcpy_host}:{config.scrcpy_port}{path}"
    await client_ws.accept()
    try:
        async with websockets.connect(backend_url) as backend_ws:
            async def forward_to_client():
                try:
                    async for msg in backend_ws:
                        if isinstance(msg, bytes):
                            await client_ws.send_bytes(msg)
                        else:
                            await client_ws.send_text(msg)
                except Exception:
                    pass

            async def forward_to_backend():
                try:
                    while True:
                        data = await client_ws.receive()
                        if "text" in data and data["text"]:
                            await backend_ws.send(data["text"])
                        elif "bytes" in data and data["bytes"]:
                            await backend_ws.send(data["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(forward_to_client()),
                 asyncio.create_task(forward_to_backend())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except Exception as e:
        logger.warning("WebSocket proxy error (%s): %s", path, e)
    finally:
        try:
            await client_ws.close()
        except Exception:
            pass


@app.websocket("/ws/video")
async def ws_video(ws: WebSocket):
    await _ws_proxy(ws, "/ws/video")


@app.websocket("/ws/control")
async def ws_control(ws: WebSocket):
    await _ws_proxy(ws, "/ws/control")


# Register API routes
from scrcpy_ai.web.routes import router  # noqa: E402
app.include_router(router)

# Serve static files (web UI) — must be last (catch-all mount)
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def main():
    parser = argparse.ArgumentParser(description="scrcpy AI web server")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    parser.add_argument("--scrcpy-port", type=int, default=18080,
                        help="scrcpy internal API port")
    parser.add_argument("--api-key", type=str, default="", help="OpenRouter API key")
    parser.add_argument("--model", type=str, default="", help="LLM model")
    parser.add_argument("--vision-model", type=str, default="", help="VLM model")
    args = parser.parse_args()

    config.web_port = args.port
    config.scrcpy_port = args.scrcpy_port
    if args.api_key:
        config.api_key = args.api_key
    if args.model:
        config.model = args.model
    if args.vision_model:
        config.vision_model = args.vision_model

    uvicorn.run(app, host="0.0.0.0", port=config.web_port, log_level="info")


if __name__ == "__main__":
    main()
