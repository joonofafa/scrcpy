"""FastAPI application entry point."""

import argparse
import logging
import os

import uvicorn
from fastapi import FastAPI
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


# Register API routes
from scrcpy_ai.web.routes import router  # noqa: E402
app.include_router(router)

# Serve static files (web UI)
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
