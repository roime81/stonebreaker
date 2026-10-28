"""Entrypoint: optionally seed, then expose the ASGI app. Run: uvicorn app.server:app"""
import os

from .config import load_settings
from .main import create_app
from .seed import seed

_settings = load_settings()
if os.environ.get("STONEBREAKER_SEED", "true").lower() == "true":
    seed(_settings.pg_dsn)
app = create_app(_settings)
