"""Tiny JSON-on-disk store.

Render's free/paid instance filesystem is small but writable; a single JSON
document per collection keeps the deployment dependency-free (no Postgres
needed) while surviving restarts when a Disk is attached.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import settings


class JsonStore:
    def __init__(self, path: Path, initial: Any) -> None:
        self.path = path
        self.initial = initial
        self._lock = threading.RLock()
        self._data: Any = None

    # ------------------------------------------------------------------ #
    def _load(self) -> Any:
        if self._data is not None:
            return self._data
        settings.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = json.loads(json.dumps(self.initial))
        else:
            self._data = json.loads(json.dumps(self.initial))
        return self._data

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, default=str))
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ #
    def read(self) -> Any:
        with self._lock:
            return json.loads(json.dumps(self._load()))

    def mutate(self, fn) -> Any:
        """Apply ``fn(data)`` under a lock and persist the result."""
        with self._lock:
            data = self._load()
            result = fn(data)
            self._flush()
            return result if result is not None else json.loads(json.dumps(data))

    def set(self, value: Any) -> None:
        with self._lock:
            self._data = value
            self._flush()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


class DataDir:
    """Named collections used across the app."""

    def __init__(self) -> None:
        settings.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self.config = JsonStore(settings.RUNTIME_DIR / "config.json", {})
        self.accounts = JsonStore(
            settings.RUNTIME_DIR / "accounts.json", {"default_account_id": None, "items": []}
        )
        self.algos = JsonStore(settings.RUNTIME_DIR / "algos.json", {"items": []})
        self.audit = JsonStore(settings.RUNTIME_DIR / "audit.json", {"items": []})

    # ---- audit trail -------------------------------------------------
    def log_audit(self, action: str, detail: str = "", actor: str = "web") -> None:
        def _append(data: dict) -> None:
            data["items"].append(
                {"ts": now(), "action": action, "detail": detail, "actor": actor}
            )
            data["items"] = data["items"][-500:]

        self.audit.mutate(_append)

    # ---- algo source files -------------------------------------------
    @property
    def algo_dir(self) -> Path:
        path = settings.RUNTIME_DIR / "algos"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_algo_source(self, algo_id: str, content: str) -> int:
        path = self.algo_dir / f"{algo_id}.py"
        path.write_text(content, encoding="utf-8")
        return len(content.encode())

    def read_algo_source(self, algo_id: str) -> str:
        path = self.algo_dir / f"{algo_id}.py"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_algo_ea(self, algo_id: str, content: str) -> Path:
        path = self.algo_dir / f"{algo_id}.mq5"
        path.write_text(content, encoding="utf-8")
        return path


data = DataDir()
