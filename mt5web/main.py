"""FastAPI application factory and HTTP/WS routes for the MT5 Web Console."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any

from contextlib import asynccontextmanager

from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import MQL5, algo, auth, broker, market
from .config import settings
from .gateway import GatewayError, err_text
from .hub import HubError, hub
from .models import (
    AccountIn,
    AlgoCreate,
    AlgoRunRequest,
    AlgoUpdate,
    LoginRequest,
    OrderRequest,
    PositionClose,
    PositionModify,
    PreviewRequest,
    SettingsPatch,
    SymbolAdd,
)
from .store import data, now

log = logging.getLogger("mt5web.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Boot-time self check so the log tells you exactly what is wired up."""
    info = broker._platform()
    log.info(
        "%s v%s starting on %s %s (python %s, render=%s)",
        settings.APP_NAME, settings.VERSION, info["system"], info["release"], info["python"], info["render"],
    )
    log.info("MetaTrader5 python package: %s", "importable" if broker._mt5_package_available() else "NOT available on this OS (Windows-only) - use the Bridge agent")
    log.info("bridge key ready: %s | passcode set: %s", auth.passcode_is_set() or bool(settings.expected_bridge_key()), auth.passcode_is_set())
    if cfg().get("kill_switch"):
        log.warning("kill switch is engaged at boot; new orders stay blocked until it is released")
    try:
        yield
    finally:
        market.stop_all()
        with contextlib.suppress(Exception):
            await algo.stop_all("app shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Control a MetaTrader 5 terminal (login, symbols, algo deployment, live trading) "
        "from a web dashboard. The terminal runs on Windows; this service is the control "
        "plane and talks to it either in-process (Windows) or through the Bridge agent."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
api = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
):
    token = auth.token_from_request(authorization, x_token or token)
    payload = auth.verify_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="not authenticated - sign in with the app passcode")
    return payload


def cfg() -> dict:
    return data.config.read()


# --------------------------------------------------------------------------- #
# app state / auth
# --------------------------------------------------------------------------- #


@api.get("/health")
async def health() -> dict:
    return {"ok": True, "ts": now(), "agents": len(hub.agents)}


@api.get("/state")
async def state(_: dict = Depends(require_token)) -> dict:
    snap = broker.status_summary()
    snap["market"] = market.loop_status()
    snap["algos"] = algo.list_algos()
    snap["needs_setup"] = auth.needs_setup()
    snap["public_origin"] = settings.public_origin() or None
    return snap


@api.post("/auth/login")
async def login(payload: LoginRequest) -> dict:
    if auth.needs_setup():
        if len(payload.passcode) < 6:
            raise HTTPException(400, "first run: choose a passcode of at least 6 characters")
        auth.set_passcode(payload.passcode)
        data.log_audit("auth.setup", "initial passcode created")
        return {"token": auth.make_token("owner"), "role": "owner", "expires_in": 7 * 24 * 3600, "first_run": True}
    if not auth.verify_passcode(payload.passcode):
        await asyncio.sleep(0.4)  # slow down brute force
        raise HTTPException(401, "wrong passcode")
    return {"token": auth.make_token("owner"), "role": "owner", "expires_in": 7 * 24 * 3600}


@api.get("/auth/status")
async def auth_status() -> dict:
    return {"needs_setup": auth.needs_setup(), "secured": auth.passcode_is_set()}


@api.post("/auth/change-passcode")
async def change_passcode(payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    raw = str(payload.get("passcode") or "")
    if len(raw) < 6:
        raise HTTPException(400, "passcode must be at least 6 characters")
    auth.set_passcode(raw)
    data.log_audit("auth.passcode", "changed")
    return {"ok": True}


@api.get("/platform")
async def platform_probe(_: dict = Depends(require_token)) -> dict:
    """Tell the user whether MT5 could run on *this* host (and what is missing)."""
    import shutil
    from pathlib import Path as _P

    env = {}
    for name in ("WINEPREFIX", "WINE", "DISPLAY"):
        env[name] = os.environ.get(name)
    home = _P.home()
    wine_prefix = _P(env.get("WINEPREFIX") or (home / ".mt5"))
    term_dir = wine_prefix / "drive_c" / "Program Files" / "MetaTrader 5"
    out = {
        "system": broker._platform(),
        "wine_binary": shutil.which("wine") or shutil.which("wine64"),
        "xvfb_binary": shutil.which("Xvfb"),
        "wine_prefix": str(wine_prefix),
        "mt5_in_prefix": term_dir.exists(),
        "terminal_exe": str(term_dir / "terminal64.exe") if term_dir.exists() else None,
        "mt5_package": broker._mt5_package_available(),
        "can_run_mt5_natively": False,
        "env": {k: v for k, v in env.items() if v},
        "verdict": "",
    }
    if out["system"]["is_windows"]:
        out["can_run_mt5_natively"] = True
        out["verdict"] = "Windows host: install MetaTrader5 + run this app locally, the agent is optional."
    elif out["wine_binary"] and out["mt5_in_prefix"]:
        out["can_run_mt5_natively"] = True
        out["verdict"] = (
            "MT5 found under Wine on this Linux host. The MetaTrader5 python package still needs a *Windows* "
            "python (inside Wine), so run agents/agent/main.py in that Wine python and point it here."
        )
    elif out["wine_binary"]:
        out["verdict"] = "Wine present but no MetaTrader 5 prefix found - run agents/setup-mt5-wine.sh."
    else:
        out["verdict"] = (
            "This Linux host has no Wine: MT5 cannot run here. Deploy this app (Render) and run the Bridge "
            "agent on Windows, or install Wine + MT5 on your own Linux box with xvfb for headless use."
        )
    return out


@api.post("/settings")
async def patch_settings(payload: SettingsPatch, _: dict = Depends(require_token)) -> dict:
    def _mutate(store: dict) -> None:
        if payload.symbols is not None:
            store["symbols"] = [s.upper() for s in payload.symbols][:60]
        if payload.max_lot is not None:
            store["max_lot"] = payload.max_lot
        if payload.kill_switch is not None:
            store["kill_switch"] = payload.kill_switch
        if payload.allow_live_trading is not None:
            store["allow_live_trading"] = payload.allow_live_trading
        if payload.tick_interval is not None:
            store["tick_interval"] = payload.tick_interval
        store["updated_at"] = time.time()

    data.config.mutate(_mutate)
    if payload.kill_switch:
        asyncio.create_task(algo.stop_all("kill switch engaged"))
        data.log_audit("settings.kill_switch", "engaged - all algos stopped")
    return cfg()


# --------------------------------------------------------------------------- #
# accounts (MT5 login / password / server)
# --------------------------------------------------------------------------- #


@api.get("/accounts")
async def list_accounts(_: dict = Depends(require_token)) -> dict:
    store = data.accounts.read()
    return {
        "default_account_id": store.get("default_account_id"),
        "items": [broker.public_account(i, store.get("default_account_id")) for i in store["items"]],
    }


@api.post("/accounts")
async def save_account(payload: AccountIn, _: dict = Depends(require_token)) -> dict:
    rec = broker.create_account(payload)
    try:
        info = await broker.connect(rec["id"])
    except (GatewayError, HubError) as exc:
        return {"account": broker.public_account(rec, rec["id"]), "connected": False, "error": str(exc)}
    return {"account": broker.public_account(rec, rec["id"]), "connected": True, "info": info}


@api.patch("/accounts/{account_id}")
async def patch_account(account_id: str, payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    try:
        rec = broker.update_account(account_id, payload or {})
    except KeyError:
        raise HTTPException(404, "account not found") from None
    return broker.public_account(rec, cfg().get("default_account_id"))


@api.delete("/accounts/{account_id}")
async def delete_account(account_id: str, _: dict = Depends(require_token)) -> dict:
    broker.delete_account(account_id)
    return {"deleted": account_id}


@api.post("/accounts/connect")
async def connect_account(account_id: str | None = Query(default=None), _: dict = Depends(require_token)) -> dict:
    try:
        info = await broker.connect(account_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "account": info}


@api.post("/accounts/disconnect")
async def disconnect_account(account_id: str | None = Query(default=None), _: dict = Depends(require_token)) -> dict:
    with contextlib.suppress(Exception):
        await broker.disconnect(account_id)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# symbols / market data
# --------------------------------------------------------------------------- #


@api.get("/symbols")
async def get_symbols(_: dict = Depends(require_token)) -> dict:
    return {"items": await broker.get_symbols()}


@api.post("/symbols")
async def add_symbols(payload: SymbolAdd, _: dict = Depends(require_token)) -> dict:
    try:
        return await broker.add_symbols(payload.symbols)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.delete("/symbols/{symbol}")
async def remove_symbol(symbol: str, _: dict = Depends(require_token)) -> dict:
    return {"symbols": await broker.remove_symbol(symbol)}


@api.get("/market/rates")
async def get_rates(symbol: str, timeframe: str = "M5", bars: int = 200, _: dict = Depends(require_token)) -> dict:
    try:
        return await broker.get_rates(symbol.upper(), timeframe.upper(), min(max(bars, 30), 1500))
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/market/quote")
async def get_quote(symbols: str | None = Query(default=None), _: dict = Depends(require_token)) -> dict:
    names = [s.upper() for s in symbols.split(",")] if symbols else None
    try:
        return {"prices": await broker.get_tick(names), "cache": market.prices}
    except (GatewayError, HubError) as exc:
        return {"prices": {}, "cache": market.prices, "error": str(exc)}


# --------------------------------------------------------------------------- #
# trading
# --------------------------------------------------------------------------- #


@api.post("/trade/order")
async def place_order(payload: OrderRequest, _: dict = Depends(require_token)) -> dict:
    try:
        return await broker.submit_order(payload)
    except (GatewayError, HubError) as exc:
        code = 409 if getattr(exc, "code", None) in (10031,) else 400
        raise HTTPException(code, str(exc)) from exc


@api.get("/trade/state")
async def trade_state(account_id: str | None = Query(default=None), _: dict = Depends(require_token)) -> dict:
    try:
        return await broker.positions_and_orders(account_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/trade/history")
async def trade_history(days: int = 7, account_id: str | None = Query(default=None), _: dict = Depends(require_token)) -> dict:
    to_ts = time.time()
    from_ts = to_ts - days * 86400
    try:
        return await broker.history(from_ts, to_ts, account_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/trade/close")
async def trade_close(payload: PositionClose, _: dict = Depends(require_token)) -> dict:
    try:
        return await broker.close_position(payload.ticket, payload.volume, payload.account_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/trade/modify")
async def trade_modify(payload: PositionModify, _: dict = Depends(require_token)) -> dict:
    if payload.stop_loss is None and payload.take_profit is None:
        raise HTTPException(400, "provide stop_loss and/or take_profit")
    try:
        return await broker.modify_position(payload.ticket, payload.stop_loss, payload.take_profit, payload.account_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/trade/cancel-order")
async def cancel_order(payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    ticket = int(payload.get("ticket") or 0)
    if not ticket:
        raise HTTPException(400, "ticket required")
    try:
        return await broker.delete_order(ticket, payload.get("account_id"))
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/trade/risk")
async def risk_preview(
    balance: float = Query(gt=0),
    risk_percent: float = Query(gt=0, le=100),
    sl_points: float = Query(gt=0),
    symbol: str = "EURUSD",
    _: dict = Depends(require_token),
) -> dict:
    meta: dict = {}
    with contextlib.suppress(Exception):
        meta = next((s for s in await broker.get_symbols() if s["name"] == symbol.upper()), {}) or {}
    lots = broker.estimate_lots(balance, risk_percent, sl_points, meta or {"point": 1e-5})
    return {
        "balance": balance,
        "risk_percent": risk_percent,
        "sl_points": sl_points,
        "symbol": symbol,
        "risk_money": round(balance * risk_percent / 100.0, 2),
        "suggested_lots": lots,
        "meta": meta,
    }


# --------------------------------------------------------------------------- #
# algos
# --------------------------------------------------------------------------- #


@api.get("/algos")
async def list_algos(_: dict = Depends(require_token)) -> dict:
    return {"items": algo.list_algos()}


@api.post("/algos")
async def create_algo(payload: AlgoCreate, _: dict = Depends(require_token)) -> dict:
    try:
        rec = algo.create_algo(payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return algo.public_algo(rec)


@api.get("/algos/{algo_id}")
async def get_algo(algo_id: str, _: dict = Depends(require_token)) -> dict:
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    return algo.public_algo(rec)


@api.patch("/algos/{algo_id}")
async def patch_algo(algo_id: str, payload: AlgoUpdate, _: dict = Depends(require_token)) -> dict:
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        rec = algo.update_algo(algo_id, patch)
    except KeyError:
        raise HTTPException(404, "algo not found") from None
    return algo.public_algo(rec)


@api.delete("/algos/{algo_id}")
async def delete_algo(algo_id: str, _: dict = Depends(require_token)) -> dict:
    await algo.stop_algo(algo_id, "deleted")
    algo.delete_algo(algo_id)
    return {"deleted": algo_id}


@api.get("/algos/{algo_id}/source")
async def get_source(algo_id: str, _: dict = Depends(require_token)) -> dict:
    return {"source": algo.read_source(algo_id)}


@api.put("/algos/{algo_id}/source")
async def put_source(algo_id: str, payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    source = str(payload.get("source", ""))
    if len(source.encode()) > 200_000:
        raise HTTPException(413, "source too large (max 200 KB)")
    try:
        rec = algo.set_source(algo_id, source)
    except KeyError:
        raise HTTPException(404, "algo not found") from None
    err = None
    if rec.get("engine") in ("python", "hybrid") and source.strip():
        try:
            algo.compile_strategy(source)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
    return {"ok": err is None, "error": err, "algo": algo.public_algo(rec)}


@api.get("/algos/{algo_id}/ea")
async def get_ea(algo_id: str, download: bool = Query(default=False), _: dict = Depends(require_token)) -> Any:
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    source = MQL5.generate_ea(rec, algo.read_source(algo_id) if rec["engine"] == "mql5" else "")
    if download:
        return StreamingResponse(
            iter([source.encode()]),
            media_type="text/plain",
            headers={"content-disposition": f"attachment; filename=MQL5_{rec['name']}.mq5"},
        )
    return {"ea_source": source, "signal_file": MQL5.file_names(rec)[2]}


@api.post("/algos/preview")
async def preview_algo(payload: PreviewRequest, _: dict = Depends(require_token)) -> dict:
    try:
        return await algo.preview(payload)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"{exc.__class__.__name__}: {exc}") from exc


@api.post("/algos/{algo_id}/backtest")
async def backtest(algo_id: str, bars: int = Query(default=800, ge=100, le=3000), _: dict = Depends(require_token)) -> dict:
    try:
        return await algo.backtest_algo(algo_id, bars)
    except KeyError:
        raise HTTPException(404, "algo not found") from None
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/algos/{algo_id}/run")
async def run_algo(algo_id: str, payload: AlgoRunRequest | None = None, _: dict = Depends(require_token)) -> dict:
    payload = payload or AlgoRunRequest()
    if cfg().get("kill_switch"):
        raise HTTPException(409, "Kill Switch is engaged - turn it off in Settings first")
    try:
        return await algo.start_algo(algo_id, payload.lookback_bars, payload.replay, payload.trade_on_replay)
    except KeyError:
        raise HTTPException(404, "algo not found") from None
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/algos/{algo_id}/stop")
async def stop_algo(algo_id: str, _: dict = Depends(require_token)) -> dict:
    try:
        return await algo.stop_algo(algo_id)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/algos/{algo_id}/log")
async def algo_log(algo_id: str, since: float = 0.0, limit: int = 200, _: dict = Depends(require_token)) -> dict:
    return {"lines": algo.get_log(algo_id, since, min(limit, 500))}


@api.get("/algos/{algo_id}/mt5-log")
async def mt5_log(algo_id: str, lines: int = 120, _: dict = Depends(require_token)) -> dict:
    """Tail the terminal's Experts/Journal log on the agent machine."""
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    try:
        conn = broker.connection(rec.get("account_id"))
        rows = await conn.tail_terminal_logs(lines)
        return {"lines": rows, "source": "terminal"}
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/algos/{algo_id}/deploy")
async def deploy_algo(algo_id: str, _: dict = Depends(require_token)) -> dict:
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    try:
        result = await MQL5.deploy(rec, algo.read_source(algo_id) if rec["engine"] == "mql5" else "")
    except (MQL5.DeployError, HubError, GatewayError) as exc:
        raise HTTPException(400, str(exc)) from exc
    def _mutate(store: dict) -> None:
        row = next((i for i in store["items"] if i["id"] == algo_id), None)
        if row:
            row["deploy"] = result.get("deploy", {})
            row["updated_at"] = now()

    data.algos.mutate(_mutate)
    return result


@api.post("/algos/{algo_id}/signal")
async def push_signal(algo_id: str, payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    action = str(payload.get("action", "none")).lower()
    try:
        return await MQL5.push_signal(rec, action)
    except (GatewayError, HubError) as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/algos/{algo_id}/signal-file")
async def signal_file(algo_id: str, _: dict = Depends(require_token)) -> dict:
    rec = algo.get_algo(algo_id)
    if not rec:
        raise HTTPException(404, "algo not found")
    return {"path": MQL5.file_names(rec)[2], "content": MQL5.signal_payload(rec)}


# --------------------------------------------------------------------------- #
# bridge / agent
# --------------------------------------------------------------------------- #


@api.get("/bridge")
async def bridge_info(_: dict = Depends(require_token)) -> dict:
    origin = settings.public_origin() or ""
    return {
        "agents": hub.list_agents(),
        "bridge_key": auth.ensure_bridge_key(),
        "ws_path": "/ws/agent",
        "origin": origin or None,
        "install_snippets": _install_snippets(origin),
        "recommended": "Windows + MT5 installed + this repo's agents/ folder",
    }


def _install_snippets(origin: str) -> dict:
    key = auth.ensure_bridge_key()
    target = origin or "https://YOUR-APP.onrender.com"
    return {
        "requirements": "python -m pip install MetaTrader5 websockets",
        "run": f'set MT5WEB_URL={target}/ws/agent && set MT5WEB_KEY={key} && python agents/agent/main.py',
        "powershell": (
            f"$env:MT5WEB_URL='{target}/ws/agent'; $env:MT5WEB_KEY='{key}'; "
            "python .\\agents\\agent\\main.py"
        ),
    }


@api.post("/bridge/rotate-key")
async def rotate_key(_: dict = Depends(require_token)) -> dict:
    key = auth.rotate_bridge_key()
    data.log_audit("bridge.rotate_key", "")
    return {"bridge_key": key}


@api.get("/bridge/agent-config")
async def agent_config(_: dict = Depends(require_token)) -> dict:
    origin = settings.public_origin() or ""
    config = {
        "url": f"{origin}/ws/agent" if origin else "/ws/agent",
        "key": auth.ensure_bridge_key(),
        "name": "mt5-agent",
        "auto_install_mt5": True,
        "auto_start_terminal": True,
        "mt5_download_url": settings.MT5_DOWNLOAD_URL,
        "terminal_path": None,
    }
    return config


@api.post("/bridge/agent-config")
async def save_agent_preferred(payload: dict = Body(...), _: dict = Depends(require_token)) -> dict:
    def _mutate(store: dict) -> None:
        if "preferred_agent_id" in payload:
            store["preferred_agent_id"] = payload["preferred_agent_id"]
        if "auto_start_terminal" in payload:
            store["auto_start_terminal"] = bool(payload["auto_start_terminal"])

    data.config.mutate(_mutate)
    return {"ok": True}


@api.get("/bridge/audit")
async def audit(limit: int = 100, _: dict = Depends(require_token)) -> dict:
    rows = data.audit.read()["items"][-limit:]
    return {"items": list(reversed(rows))}


# --------------------------------------------------------------------------- #
# agent WebSocket protocol
# --------------------------------------------------------------------------- #


@app.websocket("/ws/agent")
async def agent_socket(ws: WebSocket, key: str = Query(default="")) -> None:
    """Bridge agent endpoint: RPC over JSON frames."""
    supplied = key or ws.headers.get("x-mt5-key", "")
    if not auth.verify_bridge_key(supplied):
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = None
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        if hello.get("t") != "hello":
            await ws.close(code=4400)
            return
        conn = await hub.register(hello.get("name", "agent"), ws, hello)
        await ws.send_text(json.dumps({"t": "welcome", "agent_id": conn.agent_id, "server": settings.APP_NAME}))
        hub.agent_logs.publish({"ts": now(), "type": "info", "text": f"agent '{conn.name}' connected"})
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("t")
            if kind in ("rpc_result", "rpc_error"):
                conn.resolve({"id": msg.get("id"), "ok": kind == "rpc_result", "result": msg.get("result"), "error": msg.get("error"), "code": msg.get("code")})
            elif kind == "event":
                conn.last_seen = time.time()
                conn.push_event(msg)
                _ingest_agent_event(msg)
            elif kind == "pong":
                conn.last_seen = time.time()
            elif kind == "rpc":
                # agent-initiated call (the EA signal/file proxy, mostly)
                await _handle_agent_rpc(ws, conn, msg)
            else:
                await ws.send_text(json.dumps({"t": "pong"}))
    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            await ws.close(code=4408, reason="hello timeout")
    except Exception as exc:  # noqa: BLE001
        log.warning("agent socket error: %s", exc)
    finally:
        if conn is not None:
            await hub.unregister(conn)
            hub.agent_logs.publish({"ts": now(), "type": "info", "text": f"agent '{conn.name}' disconnected"})


def _ingest_agent_event(msg: dict) -> None:
    event = msg.get("event")
    payload = msg.get("payload") or {}
    if event == "log":
        hub.agent_logs.publish({"ts": now(), "type": "mt5_log", **payload})
    elif event == "tick":
        market.prices[payload.get("symbol", "")] = {**payload, "ts": now()}
        market.hub_publish({payload.get("symbol", ""): {**payload, "ts": now()}})
    elif event == "trade":
        hub.trade_events.publish({"ts": now(), "type": "mt5_trade", **payload})


async def _handle_agent_rpc(ws: WebSocket, conn, msg: dict) -> None:
    rid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    ok = True
    result: Any = None
    error: str | None = None
    if method == "algo_log":
        algo.append_log(params.get("algo_id", ""), params.get("text", ""), params.get("level", "info"))
    elif method == "algo_signal":
        rec = algo.get_algo(params.get("algo_id", ""))
        if rec:
            def _mutate(store: dict) -> None:
                row = next((i for i in store["items"] if i["id"] == rec["id"]), None)
                if row:
                    row.setdefault("stats", {})["ea_signal"] = params
                    row["updated_at"] = now()

            data.algos.mutate(_mutate)
    else:
        ok, error = False, f"unknown agent-initiated method '{method}'"
    await ws.send_text(json.dumps({"t": "rpc_result" if ok else "rpc_error", "id": rid, "result": result, "error": error}))


# --------------------------------------------------------------------------- #
# browser WebSocket streams
# --------------------------------------------------------------------------- #


@app.websocket("/ws/stream")
async def browser_stream(ws: WebSocket, token: str = Query(default=""), symbols: str = Query(default="")) -> None:
    """Single multiplexed stream for the dashboard: quotes, algo logs, trade events."""
    if not auth.verify_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    wanted = {s.upper() for s in symbols.split(",") if s} or None
    fans = {"tick": hub.ticks, "log": hub.agent_logs, "event": hub.trade_events}
    tasks: dict[asyncio.Task, str] = {}
    queues = {name: fan.subscribe() for name, fan in fans.items()}
    try:
        await ws.send_text(
            json.dumps(
                {
                    "t": "hello",
                    "prices": {k: v for k, v in market.prices.items() if not wanted or k in wanted},
                    "algos": algo.list_algos(),
                    "state": broker.status_summary(),
                },
                default=str,
            )
        )
        tasks = {asyncio.create_task(q.get()): name for name, q in queues.items()}
        last_ping = time.time()
        # (tasks is re-bound in the loop; initialised here so finally is always valid)
        while True:
            done, _ = await asyncio.wait(set(tasks), timeout=25.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await ws.send_text(json.dumps({"t": "ping", "ts": now()}))
                last_ping = time.time()
                continue
            for task in done:
                name = tasks.pop(task)
                item = task.result()
                queue = queues[name]
                tasks[asyncio.create_task(queue.get())] = name
                if name == "tick" and wanted and item.get("symbol") not in wanted:
                    continue
                await ws.send_text(json.dumps({"t": name, "data": item}, default=str))
            if time.time() - last_ping > 25:
                last_ping = time.time()
                await ws.send_text(json.dumps({"t": "ping", "ts": now()}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for name, queue in queues.items():
            fans[name].unsubscribe(queue)
        for task in tasks:
            task.cancel()


# --------------------------------------------------------------------------- #
# static frontend
# --------------------------------------------------------------------------- #


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    html = settings.STATIC_DIR / "index.html"
    if not html.exists():  # pragma: no cover
        return HTMLResponse("<h1>MT5 Web Console</h1><p>frontend missing</p>", status_code=500)
    body = html.read_text(encoding="utf-8")
    boot = {
        "needs_setup": auth.needs_setup(),
        "state": broker.status_summary(),
        "origin": settings.public_origin(),
        "version": settings.VERSION,
    }
    body = body.replace(
        "</head>",
        f"<script>window.__BOOT__={json.dumps(boot, default=str)};</script></head>",
        1,
    )
    return HTMLResponse(body, headers={"cache-control": "no-store"})


@api.get("/bridge/download", include_in_schema=False)
async def bridge_download(_: dict = Depends(require_token)) -> StreamingResponse:
    """Zip of the whole agents/ folder (agent + scripts + requirements)."""
    import io
    import zipfile

    root = settings.STATIC_DIR.parent.parent / "agents"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_dir() or any(part in {"__pycache__", ".venv"} for part in path.parts):
                    continue
                zf.write(path, str(path.relative_to(root.parent)))
        else:  # pragma: no cover
            zf.writestr("README.txt", "agents/ folder missing in this deployment")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="mt5-bridge-agent.zip"'},
    )


@app.get("/agent/agent.py", include_in_schema=False)
async def agent_source(_: dict = Depends(require_token)) -> FileResponse:
    """Serve the single-file agent so it can be downloaded straight from the web app."""
    path = settings.RUNTIME_DIR / "mt5_bridge_agent.py"
    if not path.exists():
        agent_file = settings.STATIC_DIR.parent.parent / "agents" / "agent" / "main.py"
        if not agent_file.exists():
            raise HTTPException(404, "agent bundle not found on this server")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_file.read_text(encoding="utf-8"), encoding="utf-8")
    return FileResponse(path, media_type="text/plain", filename="mt5_bridge_agent.py")


@app.exception_handler(GatewayError)
async def gateway_exception_handler(_: Request, exc: GatewayError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc), "code": exc.code})


@app.exception_handler(HubError)
async def hub_exception_handler(_: Request, exc: HubError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc), "hint": err_text(-10005)})


app.include_router(api)

# static assets (css/js) - index.html is served by the route above so the boot
# payload can be injected
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")
app.mount("/", StaticFiles(directory=str(settings.STATIC_DIR), html=False), name="assets")
