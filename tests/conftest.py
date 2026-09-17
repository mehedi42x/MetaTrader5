"""Shared test fixtures: every test runs against an isolated data dir."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Point all runtime state at a temp dir *before* mt5web modules load it."""
    monkeypatch.setenv("MT5WEB_DATA", str(tmp_path / "runtime"))
    monkeypatch.setenv("MT5WEB_RUNTIME", str(tmp_path / "runtime" / "runtime"))
    monkeypatch.setenv("MT5WEB_SECRET", "test-secret-" + uuid.uuid4().hex)
    monkeypatch.delenv("MT5WEB_PASSCODE", raising=False)
    monkeypatch.delenv("MT5WEB_BRIDGE_KEY", raising=False)
    for name in [m for m in sys.modules if m.startswith("mt5web")]:
        del sys.modules[name]
    yield tmp_path


@pytest.fixture()
def app(isolated_env):
    from mt5web.main import app as application

    return application


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed_client(client):
    """Signed-in client: creates the passcode on first run and stores the token."""
    r = client.post("/api/auth/login", json={"passcode": "test-pass-123"})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = "Bearer " + r.json()["token"]
    return client
