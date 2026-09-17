"""HTTP surface tests: auth, settings, accounts, algos, guards, static app."""

from __future__ import annotations

import pytest


def test_health_is_open_and_docs_are_disabled(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/docs").status_code == 200  # docs are enabled on /api/docs
    assert client.get("/docs").status_code == 404


def test_frontend_is_served_with_boot_payload(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "__BOOT__" in body and "MT5 Web Console" in body
    for asset in ("/static/app.css", "/static/core.js", "/static/views.js", "/static/views2.js", "/static/views3.js", "/static/app.js"):
        assert client.get(asset).status_code == 200, asset


def test_login_is_required_and_passcode_setup_is_one_shot(authed_client):
    r = authed_client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["needs_setup"] is False
    # wrong passcode now fails
    c2 = authed_client
    assert c2.post("/api/auth/login", json={"passcode": "nope"}).status_code == 401
    # a fresh client cannot read state without a token
    from fastapi.testclient import TestClient

    with TestClient(authed_client.app) as fresh:
        assert fresh.get("/api/state").status_code == 401


def test_short_passcodes_are_refused_on_first_run(isolated_env):
    from fastapi.testclient import TestClient

    from mt5web.main import app

    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"passcode": "abc"}).status_code == 400


def test_settings_symbols_and_kill_switch(authed_client):
    s = authed_client.post("/api/settings", json={"max_lot": 0.5, "tick_interval": 3})
    assert s.status_code == 200 and s.json()["max_lot"] == 0.5

    r = authed_client.post("/api/symbols", json={"symbols": ["EURJPY", "usdcad"]})
    assert r.status_code == 200
    assert "EURJPY" in r.json()["symbols"]
    assert "USDCAD" in r.json()["symbols"]  # normalised to upper case

    remaining = authed_client.delete("/api/symbols/USDCAD").json()["symbols"]
    assert "USDCAD" not in remaining and "EURJPY" in remaining

    assert authed_client.post("/api/settings", json={"kill_switch": True}).json()["kill_switch"] is True
    assert authed_client.get("/api/state").json()["kill_switch"] is True


def test_invalid_settings_are_rejected(authed_client):
    assert authed_client.post("/api/settings", json={"max_lot": 0}).status_code == 422
    assert authed_client.post("/api/settings", json={"max_lot": 9999}).status_code == 422


def test_account_crud_without_agent_reports_actionable_error(authed_client):
    payload = {
        "name": "Demo", "server": "Demo-Server", "login": 1234567,
        "password": "secret-pw", "make_default": True,
    }
    r = authed_client.post("/api/accounts", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is False
    assert "agent" in body["error"].lower() or "MetaTrader5" in body["error"]

    listing = authed_client.get("/api/accounts").json()
    assert len(listing["items"]) == 1
    saved = listing["items"][0]
    assert saved["has_password"] is True
    assert saved["status"] == "error"
    # the password must never be echoed back
    assert "secret-pw" not in authed_client.get("/api/accounts").text

    upd = authed_client.patch(f"/api/accounts/{saved['id']}", json={"name": "Renamed"})
    assert upd.json()["name"] == "Renamed"
    assert authed_client.delete(f"/api/accounts/{saved['id']}").json()["deleted"] == saved["id"]
    assert authed_client.get("/api/accounts").json()["items"] == []


def test_order_validation_and_guards(authed_client):
    assert authed_client.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "hold", "volume": 0.1}).status_code == 422
    assert authed_client.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "buy", "volume": -1}).status_code == 422
    # no account -> friendly error, not a 500
    r = authed_client.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "buy", "volume": 0.1})
    assert r.status_code == 400
    assert "account" in r.json()["detail"].lower() or "10008" in str(r.json().get("code"))


def test_algo_crud_source_and_ea_generation(authed_client):
    created = authed_client.post(
        "/api/algos",
        json={
            "name": "Trend Rider", "engine": "python", "symbol": "EURUSD", "timeframe": "M5",
            "volume": 0.02, "stop_loss_points": 300, "take_profit_points": 600,
            "description": "ema cross", "magic": 5150,
        },
    )
    assert created.status_code == 200, created.text
    algo_id = created.json()["id"]
    assert created.json()["has_source"] is True  # starter code was auto-attached

    assert authed_client.post(
        "/api/algos", json={"name": "Trend Rider", "engine": "python", "symbol": "EURUSD"}
    ).status_code == 409

    bad = authed_client.put(
        f"/api/algos/{algo_id}/source", json={"source": "def on_bar(ctx, bars, i)\n  return 1"}
    )
    assert bad.status_code == 200
    assert bad.json()["ok"] is False and "syntax error" in bad.json()["error"]

    good = authed_client.put(
        f"/api/algos/{algo_id}/source",
        json={"source": "def on_bar(ctx, bars, i):\n    return 1 if i % 7 == 0 else None\n"},
    )
    assert good.json()["ok"] is True

    assert authed_client.get(f"/api/algos/{algo_id}").json()["magic"] == 5150
    patched = authed_client.patch(f"/api/algos/{algo_id}", json={"volume": 0.05, "trailing_points": 120})
    assert patched.json()["volume"] == 0.05 and patched.json()["trailing_points"] == 120

    ea = authed_client.get(f"/api/algos/{algo_id}/ea").json()
    assert "OnTick" in ea["ea_source"] and ea["signal_file"].startswith("MQL5/Files/")

    sig = authed_client.get(f"/api/algos/{algo_id}/signal-file").json()
    assert "signal=" in sig["content"]

    # live run without a terminal must fail cleanly, not hang or 500
    run = authed_client.post(f"/api/algos/{algo_id}/run", json={"lookback_bars": 100, "replay": False})
    assert run.status_code == 400
    assert authed_client.get(f"/api/algos/{algo_id}").json()["status"] in ("error", "stopped")

    assert authed_client.delete(f"/api/algos/{algo_id}").json()["deleted"] == algo_id
    assert authed_client.get(f"/api/algos/{algo_id}").status_code == 404


def test_hybrid_and_mql5_engines_validate_source(authed_client):
    hybrid = authed_client.post(
        "/api/algos",
        json={"name": "Bridge Algo", "engine": "hybrid", "symbol": "XAUUSD", "timeframe": "M15", "source": ""},
    )
    assert hybrid.status_code == 200
    assert hybrid.json()["engine"] == "hybrid"
    assert hybrid.json()["has_source"] is True  # python strategies always get a starting point

    mql5 = authed_client.post(
        "/api/algos",
        json={"name": "Pure EA", "engine": "mql5", "symbol": "XAUUSD", "timeframe": "H1", "source": ""},
    )
    assert mql5.status_code == 200 and mql5.json()["has_source"] is False
    # deploying without an agent must explain what is missing
    dep = authed_client.post(f"/api/algos/{mql5.json()['id']}/deploy")
    assert dep.status_code == 400
    assert "bridge agent" in dep.json()["detail"].lower()


def test_run_is_blocked_by_kill_switch(authed_client):
    a = authed_client.post("/api/algos", json={"name": "Guarded", "engine": "python", "symbol": "EURUSD"}).json()
    authed_client.post("/api/settings", json={"kill_switch": True})
    assert authed_client.post(f"/api/algos/{a['id']}/run", json={}).status_code == 409
    authed_client.post("/api/settings", json={"kill_switch": False})


def test_bridge_endpoints(authed_client):
    b = authed_client.get("/api/bridge").json()
    assert b["agents"] == []
    assert len(b["bridge_key"]) >= 16
    assert b["ws_path"] == "/ws/agent"
    assert "MetaTrader5" in b["install_snippets"]["requirements"]

    rotated = authed_client.post("/api/bridge/rotate-key").json()["bridge_key"]
    assert rotated != b["bridge_key"]
    assert authed_client.get("/api/bridge").json()["bridge_key"] == rotated

    cfg = authed_client.get("/api/bridge/agent-config").json()
    assert cfg["url"].endswith("/ws/agent")
    assert cfg["key"] == rotated

    zip_resp = authed_client.get("/api/bridge/download")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"].startswith("application/zip")
    assert len(zip_resp.content) > 500


def test_agent_socket_rejects_bad_key(authed_client):
    with pytest.raises(Exception):
        with authed_client.websocket_connect("/ws/agent?key=definitely-wrong"):
            pass


def test_platform_probe_explains_the_windows_constraint(authed_client):
    r = authed_client.get("/api/platform")
    assert r.status_code == 200
    body = r.json()
    assert body["system"]["system"] in ("Linux", "Windows", "Darwin")
    assert "can_run_mt5_natively" in body
    assert body["mt5_package"] is False or body["system"]["is_windows"]
    assert "verdict" in body and len(body["verdict"]) > 20


def test_websocket_stream_requires_a_token(authed_client):
    with pytest.raises(Exception):
        with authed_client.websocket_connect("/ws/stream?token=bogus"):
            pass


def test_audit_trail_records_actions(authed_client):
    authed_client.post("/api/symbols", json={"symbols": ["NOKKUS"]})
    items = authed_client.get("/api/bridge/audit").json()["items"]
    assert any(row["action"] == "algo.create" or row["action"] == "account.save" or row["action"] for row in items)
    assert items, "expected at least one audit entry"
