"""ASGI entrypoint used by Render / uvicorn: ``uvicorn app:app``."""

from mt5web.main import app

__all__ = ["app"]
