"""Broker connection manager.

A "connection" is an MT5 account + the transport used to reach the terminal
(either the in-process ``MetaTrader5`` package on Windows, or a Bridge agent).
Everything the API needs (login, symbol data, orders, algo deployment) goes
through here so both transports behave identically.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import math
import time
from typing import Any

from . import crypto
from .config import settings
from .gateway import (
    BaseGateway,
    GatewayError,
    InProcessGateway,
    account_info_to_dict,
    deal_to_dict,
    err_text,
    normalize_symbol_info,
    order_to_dict,
    position_to_dict,
    round_to_step,
)
from .hub import AgentGateway, HubError, hub
from .store import data, new_id, now

log = logging.getLogger("mt5web.broker")


class MT5Connection:
    def __init__(self, account: dict) -> None:
        self.account_id = account["id"]
        self.name = account.get("name") or f"MT5 {account.get('login')}"
        self.server = account.get("server", "")
        self.login = int(account.get("login") or 0)
        self.terminal_path = account.get("terminal_path") or None
        self.gateway: BaseGateway = AgentGateway(account["id"])
        self.status = "disconnected"
        self.last_error: str | None = None
        self.connected_at: float | None = None
        self.terminal_info: dict = {}
        self._lock = asyncio.Lock()
        self._sig: str | None = None
        self._inited_for: str | None = None

    # ------------------------------------------------------------------ #
    @property
    def credential_signature(self) -> str:
        pw = account_password(self.account_id)
        return hashlib.sha256(f"{self.login}|{self.server}|{pw}".encode()).hexdigest()[:16]

    async def ensure_ready(self, force: bool = False) -> None:
        """Connect + log in to the account if we are not already on it."""
        async with self._lock:
            sig = self.credential_signature
            if not force and self.status == "connected" and sig == self._sig and self._inited_for == sig:
                return
            try:
                await self._initialize()
                self._sig = sig
                self._inited_for = sig
                self.status = "connected"
                self.last_error = None
                self.connected_at = time.time()
                await self._update_account_status()
                from . import market as _market

                if not _market.is_running(self.account_id):
                    _market.start_loop(self.account_id, self.gateway)
            except (GatewayError, HubError, Exception) as exc:  # noqa: BLE001
                self.status = "error"
                self.last_error = str(exc)
                await self._update_account_status()
                if isinstance(exc, (GatewayError, HubError)):
                    raise
                raise GatewayError(str(exc)) from exc

    async def _initialize(self) -> None:
        params: dict[str, Any] = {
            "login": self.login,
            "password": account_password(self.account_id),
            "server": self.server,
            "timeout_ms": int(self.account_field("timeout_ms") or 60000),
            "company": None,
        }
        if self.terminal_path:
            params["path"] = self.terminal_path
        if isinstance(self.gateway, InProcessGateway):
            local = {
                "path": params.get("path"),
                "login": params["login"],
                "password": params["password"],
                "server": params["server"],
                "timeout": params["timeout_ms"],
            }
            ok = await self.gateway.initialize_terminal({k: v for k, v in local.items() if v not in (None, "")})
            res = {"ok": ok}
            if not ok:
                code, text = await self.gateway.last_error()
                res["error"] = text or f"initialize() failed (code {code})"
                res["code"] = code
        else:
            res = await self.gateway.call("initialize", params)
        res = res if isinstance(res, dict) else {"ok": bool(res)}
        if not res.get("ok", True):
            raise GatewayError(
                res.get("error")
                or "MT5 initialize() failed - check login / password / server, and make sure "
                   "the terminal on the agent machine can reach that broker server",
                code=res.get("code"),
            )
        with contextlib.suppress(Exception):
            self.terminal_info = await self.gateway.call("terminal_info") or {}

    def account_field(self, key: str, default=None):
        for item in data.accounts.read()["items"]:
            if item["id"] == self.account_id:
                return item.get(key, default)
        return default

    async def _update_account_status(self) -> None:
        def _mutate(store: dict) -> None:
            for item in store["items"]:
                if item["id"] == self.account_id:
                    item["status"] = self.status
                    item["last_error"] = self.last_error
                    item["connected_at"] = self.connected_at

        data.accounts.mutate(_mutate)

    # ---- file/EA ops used by the algo deployment ---------------------- #
    async def data_folder(self) -> str:
        return str(await self.gateway.call("terminal_datafolder") or "").rstrip("\\/")

    async def compile_mq5(self, source_path: str) -> dict:
        return await self.gateway.call("terminal_compile", path=source_path)

    async def write_file(self, relpath: str, content: str, b64: bool = False) -> dict:
        return await self.gateway.call("fs_write", path=relpath, content=content, b64=b64)

    async def file_exists(self, relpath: str) -> bool:
        res = await self.gateway.call("file_exists", path=relpath)
        return bool(res.get("exists")) if isinstance(res, dict) else bool(res)

    async def tail_terminal_logs(self, lines: int = 200) -> list[dict]:
        res = await self.gateway.call("tail_logs", lines=lines)
        return res.get("lines", []) if isinstance(res, dict) else []


# --------------------------------------------------------------------------- #
# account records (encrypted password)
# --------------------------------------------------------------------------- #


def account_password(account_id: str) -> str:
    for item in data.accounts.read()["items"]:
        if item["id"] == account_id:
            try:
                return crypto.decrypt(item.get("password_enc") or "")
            except ValueError:
                return ""
    return ""


def create_account(payload) -> dict:
    """Add or replace an MT5 account (matched on login + server)."""
    enc = crypto.encrypt(payload.password)

    def _mutate(store: dict) -> dict:
        existing = next(
            (i for i in store["items"] if i["login"] == payload.login and i["server"] == payload.server),
            None,
        )
        rec = existing or {"id": new_id("acct"), "created_at": now()}
        rec.update(
            {
                "name": payload.name or f"{payload.server} {payload.login}",
                "server": payload.server,
                "login": payload.login,
                "password_enc": enc,
                "password_hint": payload.password[-2:] if len(payload.password) > 2 else "",
                "terminal_path": payload.terminal_path,
                "timeout_ms": payload.timeout_ms,
                "updated_at": now(),
                "status": "disconnected",
                "last_error": None,
            }
        )
        if existing is None:
            store["items"].append(rec)
        if payload.make_default or not store.get("default_account_id"):
            store["default_account_id"] = rec["id"]
        return rec

    rec = data.accounts.mutate(_mutate)
    _connections.pop(rec["id"], None)
    data.log_audit("account.save", f"{rec['name']} (login {rec['login']} @ {rec['server']})")
    return rec


def update_account(account_id: str, patch: dict) -> dict:
    def _mutate(store: dict) -> dict | None:
        rec = next((i for i in store["items"] if i["id"] == account_id), None)
        if not rec:
            return None
        for key in ("name", "server", "login", "terminal_path", "timeout_ms"):
            if patch.get(key) not in (None, ""):
                rec[key] = patch[key]
        if patch.get("password"):
            rec["password_enc"] = crypto.encrypt(str(patch["password"]))
            rec["password_hint"] = str(patch["password"])[-2:]
        rec["updated_at"] = now()
        rec["status"] = "disconnected"
        return rec

    rec = data.accounts.mutate(_mutate)
    if rec is None:
        raise KeyError(account_id)
    _connections.pop(account_id, None)
    return rec


def delete_account(account_id: str) -> None:
    def _mutate(store: dict) -> None:
        store["items"] = [i for i in store["items"] if i["id"] != account_id]
        if store.get("default_account_id") == account_id:
            store["default_account_id"] = store["items"][0]["id"] if store["items"] else None

    data.accounts.mutate(_mutate)
    _connections.pop(account_id, None)


def public_account(rec: dict, default_id: str | None) -> dict:
    return {
        "id": rec["id"],
        "name": rec.get("name"),
        "server": rec.get("server"),
        "login": rec.get("login"),
        "terminal_path": rec.get("terminal_path"),
        "has_password": bool(rec.get("password_enc")),
        "status": rec.get("status", "disconnected"),
        "last_error": rec.get("last_error"),
        "connected_at": rec.get("connected_at"),
        "is_default": rec["id"] == default_id,
        "updated_at": rec.get("updated_at"),
    }


def default_account() -> dict | None:
    store = data.accounts.read()
    if not store["items"]:
        return None
    wanted = store.get("default_account_id")
    return next((i for i in store["items"] if i["id"] == wanted), store["items"][0])


# --------------------------------------------------------------------------- #
# connection registry
# --------------------------------------------------------------------------- #

_connections: dict[str, MT5Connection] = {}


def connection(account_id: str | None = None) -> MT5Connection:
    store = data.accounts.read()
    account_id = account_id or store.get("default_account_id") or (store["items"][0]["id"] if store["items"] else None)
    if not account_id:
        raise GatewayError(err_text(-10008), code=-10008)
    rec = next((i for i in store["items"] if i["id"] == account_id), None)
    if rec is None:
        raise GatewayError("account not found", code=-10008)
    conn = _connections.get(account_id)
    if conn is None or conn.name != (rec.get("name") or "") or conn.login != rec.get("login"):
        conn = MT5Connection(rec)
        _connections[account_id] = conn
    return conn


def live_gateway() -> BaseGateway | None:
    """Gateway of the default account, if one exists."""
    try:
        return connection().gateway
    except GatewayError:
        return None


def gateway_for(source: str = "auto") -> BaseGateway:
    """``auto`` -> agent if connected else the in-process MetaTrader5 package."""
    if source == "local":
        return InProcessGateway()
    if hub.agents:
        return AgentGateway(None)
    return InProcessGateway()


def status_summary() -> dict:
    store = data.accounts.read()
    cfg = data.config.read()
    agents = hub.list_agents()
    default_id = store.get("default_account_id")
    conn = _connections.get(default_id) if default_id else None
    return {
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "platform": _platform(),
        "mt5_package_installed": _mt5_package_available(),
        "transport": "agent" if agents else ("local" if _mt5_package_available() else "none"),
        "agents": agents,
        "account": public_account(default_account(), default_id) if default_account() else None,
        "connection_status": conn.status if conn else "disconnected",
        "accounts": [public_account(i, default_id) for i in store["items"]],
        "kill_switch": bool(cfg.get("kill_switch")),
        "allow_live_trading": bool(cfg.get("allow_live_trading", True)),
        "max_lot": float(cfg.get("max_lot", settings.MAX_LOT)),
        "symbols": cfg.get("symbols", settings.DEFAULT_SYMBOLS),
        "needs_setup": cfg.get("needs_setup", True),
        "tick_subscribers": hub.ticks.subscriber_count,
    }


def _platform() -> dict:
    import platform
    import shutil

    return {
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
        "is_windows": platform.system() == "Windows",
        "render": bool(__import__("os").getenv("RENDER")),
        "wine": shutil.which("wine") or shutil.which("wine64"),
        "xvfb": shutil.which("Xvfb"),
    }


def _mt5_package_available() -> bool:
    if hasattr(_mt5_package_available, "_cache"):
        return _mt5_package_available._cache  # type: ignore[attr-defined]
    try:
        import importlib.util

        found = importlib.util.find_spec("MetaTrader5") is not None
    except (ImportError, ValueError):
        found = False
    _mt5_package_available._cache = found  # type: ignore[attr-defined]
    return found


# --------------------------------------------------------------------------- #
# high level operations
# --------------------------------------------------------------------------- #


async def account_snapshot(account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    info = await conn.gateway.account_info()
    return info


async def get_symbols() -> list[dict]:
    """Symbol metadata for the configured watchlist, enriched from the terminal."""
    cfg = data.config.read()
    names = cfg.get("symbols") or settings.DEFAULT_SYMBOLS
    conn = None
    with contextlib.suppress(GatewayError):
        conn = connection()
    out: list[dict] = []
    if conn:
        with contextlib.suppress(Exception):
            await conn.ensure_ready()
        results = await asyncio.gather(
            *[conn.gateway.symbol_info(name) for name in names], return_exceptions=True
        )
        for name, res in zip(names, results):
            if isinstance(res, Exception) or not res:
                out.append(normalize_symbol_info(name, None) | {"source": "app"})
            else:
                out.append({**res, "source": "terminal"})
        return out
    for name in names:
        out.append(normalize_symbol_info(name, None) | {"source": "app"})
    return out


async def add_symbols(new_symbols: list[str]) -> dict:
    def _mutate(cfg: dict) -> list[str]:
        symbols = [str(s).upper().strip() for s in cfg.get("symbols", settings.DEFAULT_SYMBOLS) if s]
        added = []
        for sym in new_symbols:
            sym = str(sym).upper().strip()
            if sym and sym not in symbols and len(symbols) < 60:
                symbols.append(sym)
                added.append(sym)
        cfg["symbols"] = symbols
        return added

    added = data.config.mutate(_mutate)
    conn = None
    with contextlib.suppress(GatewayError):
        conn = connection()
    if conn:
        await asyncio.gather(*[conn.gateway.select(sym) for sym in added], return_exceptions=True)
    return {"added": added, "symbols": data.config.read().get("symbols")}


async def remove_symbol(symbol: str) -> list[str]:
    def _mutate(cfg: dict) -> None:
        cfg["symbols"] = [s for s in cfg.get("symbols", []) if s.upper() != symbol.upper()]

    data.config.mutate(_mutate)
    return data.config.read().get("symbols", [])


async def get_rates(symbol: str, timeframe: str, bars: int) -> dict:
    conn = connection()
    await conn.ensure_ready()
    rows = await conn.gateway.rates(symbol, timeframe, bars)
    meta = await _safe_symbol_meta(conn, symbol)
    return {"symbol": symbol, "timeframe": timeframe, "bars": rows, "meta": meta}


async def _safe_symbol_meta(conn: MT5Connection, symbol: str) -> dict:
    with contextlib.suppress(Exception):
        return await conn.gateway.symbol_info(symbol)
    return normalize_symbol_info(symbol, None)


async def get_tick(symbols: list[str] | None = None) -> dict:
    cfg = data.config.read()
    names = symbols or cfg.get("symbols") or settings.DEFAULT_SYMBOLS
    conn = connection()
    await conn.ensure_ready()
    ticks = await conn.gateway.ticks(list(names))
    out = {}
    for sym in names:
        tick = ticks.get(sym)
        if tick:
            out[sym] = tick
    return out


async def positions_and_orders(account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    positions_raw, orders_raw, info = await asyncio.gather(
        conn.gateway.positions(),
        conn.gateway.orders(),
        conn.gateway.account_info(),
        return_exceptions=True,
    )
    digits = {s["name"]: s.get("digits", 5) for s in await get_symbols()}
    positions = [position_to_dict(p, digits) for p in _list(positions_raw)]
    orders = [order_to_dict(o) for o in _list(orders_raw)]
    info = info if isinstance(info, dict) else account_info_to_dict({})
    floating = sum(p["profit"] + p["swap"] + p["commission"] for p in positions)
    return {
        "positions": positions,
        "orders": orders,
        "account": info,
        "floating_profit": round(floating, 2),
        "position_count": len(positions),
    }


def _list(value: Any) -> list:
    if isinstance(value, Exception) or value is None:
        return []
    return list(value)


async def history(from_ts: float, to_ts: float, account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    deals = [deal_to_dict(d) for d in _list(await conn.gateway.history_deals(from_ts, to_ts))]
    profit = round(sum(d["profit"] + d["swap"] + d["commission"] + d["fee"] for d in deals), 2)
    closed = [d for d in deals if d["entry"] == "out"]
    wins = len([d for d in closed if d["profit"] > 0])
    return {
        "deals": sorted(deals, key=lambda d: -d["time"])[:1000],
        "summary": {
            "deals": len(deals),
            "closed": len(closed),
            "wins": wins,
            "losses": len([d for d in closed if d["profit"] <= 0]),
            "win_rate": round(100 * wins / len(closed), 1) if closed else 0.0,
            "net_profit": profit,
        },
    }


async def submit_order(payload) -> dict:
    cfg = data.config.read()
    if cfg.get("kill_switch"):
        raise GatewayError(err_text(-10007), code=-10007)
    conn = connection(payload.account_id)
    await conn.ensure_ready()

    symbol = payload.symbol.upper().strip()
    meta = await conn.gateway.symbol_info(symbol)
    if not (meta.get("description") or meta.get("bid") or meta.get("digits") not in (None, 5)):
        # symbol is not in the Market Watch yet -> select it and re-read
        with contextlib.suppress(Exception):
            await conn.gateway.select(symbol)
        meta = await conn.gateway.symbol_info(symbol)
    if not meta.get("point") and not meta.get("bid"):
        raise GatewayError(f"symbol '{symbol}' is not available on this terminal/account (not in Market Watch)")
    point = float(meta.get("point") or 1e-5)
    digits = int(meta.get("digits") or 5)

    volume = round_to_step(
        payload.volume,
        meta.get("volume_step") or 0.01,
        meta.get("volume_min") or 0.01,
        min(meta.get("volume_max") or 100, float(cfg.get("max_lot", settings.MAX_LOT))),
    )
    if volume > float(cfg.get("max_lot", settings.MAX_LOT)):
        raise GatewayError(f"Volume {volume} exceeds the app lot limit {cfg.get('max_lot')}")

    from . import market as _market

    watch = set(_market.watchlist())
    if watch and symbol not in watch:
        raise GatewayError(f"Unknown symbol {symbol!r} - add it to the symbol list first", code=10013)

    ticks = await conn.gateway.ticks([symbol])
    tick = ticks.get(symbol) or {}
    bid = float(tick.get("bid") or 0)
    ask = float(tick.get("ask") or 0)
    if not bid and not ask:
        raise GatewayError(f"no market price for {symbol} right now (market closed?)")

    order_type_map = {"buy": 0, "sell": 1, "buy_limit": 2, "sell_limit": 3, "buy_stop": 4, "sell_stop": 5}
    otype = order_type_map[payload.order_type if payload.order_type != "market" else payload.direction]
    is_buy = otype in (0, 2, 4)
    ref_price = float(payload.price or 0) or (ask if is_buy else bid)

    def _clamp(value: float | None) -> float:
        if not value:
            return 0.0
        return round(float(value), digits)

    sl = _clamp(payload.stop_loss)
    tp = _clamp(payload.take_profit)
    if not sl and payload.sl_points:
        sl = round(ref_price - payload.sl_points * point * (1 if is_buy else -1), digits)
    if not tp and payload.tp_points:
        tp = round(ref_price + payload.tp_points * point * (1 if is_buy else -1), digits)
    sl, tp = _validate_stops(sl, tp, is_buy, meta, ref_price)

    is_pending = payload.order_type != "market"
    req: dict[str, Any] = {
        "action": 3 if is_pending else 1,  # TRADE_ACTION_PENDING / TRADE_ACTION_DEAL
        "symbol": symbol,
        "volume": volume,
        "type": otype,
        "deviation": payload.deviation,
        "magic": payload.magic,
        "comment": payload.comment[:32] or "web",
        "type_time": 0,  # ORDER_TIME_GTC
        "expiration": 0,
        "type_filling": await _filling_mode(conn, symbol, meta),
        "price": round(ref_price, digits),
        "sl": sl,
        "tp": tp,
    }
    if not is_pending:
        req["price"] = round(ask if is_buy else bid, digits)

    started = time.perf_counter()
    result = await conn.gateway.place(req)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    data.log_audit(
        "order.send",
        f"{symbol} {payload.direction} {volume} @ {req['price']} -> order {result.get('order')}",
    )
    hub.trade_events.publish(
        {
            "ts": now(),
            "type": "order",
            "symbol": symbol,
            "direction": payload.direction,
            "volume": volume,
            "price": req["price"],
            "order": result.get("order"),
            "deal": result.get("deal"),
            "algo": None,
        }
    )
    return {
        "ok": True,
        "retcode": result.get("retcode"),
        "order": result.get("order"),
        "position": result.get("position", result.get("order")),
        "deal": result.get("deal"),
        "volume": volume,
        "price": req["price"],
        "sl": sl,
        "tp": tp,
        "symbol": symbol,
        "digits": digits,
        "latency_ms": elapsed_ms,
        "request": req,
    }


def _validate_stops(sl: float, tp: float, is_buy: bool, meta: dict, price: float | None = None) -> tuple[float, float]:
    digits = int(meta.get("digits") or 5)
    if price and sl:
        if is_buy and sl >= price:
            raise GatewayError(f"for a BUY the stop-loss ({sl}) must be below the entry price ({price})")
        if not is_buy and sl <= price:
            raise GatewayError(f"for a SELL the stop-loss ({sl}) must be above the entry price ({price})")
    if price and tp:
        if is_buy and tp <= price:
            raise GatewayError(f"for a BUY the take-profit ({tp}) must be above the entry price ({price})")
        if not is_buy and tp >= price:
            raise GatewayError(f"for a SELL the take-profit ({tp}) must be below the entry price ({price})")
    if sl and tp:
        if is_buy and tp <= sl:
            raise GatewayError("for a BUY, take-profit must be above stop-loss")
        if not is_buy and tp >= sl:
            raise GatewayError("for a SELL, take-profit must be below stop-loss")
    return round(sl, digits), round(tp, digits)


async def _filling_mode(conn: MT5Connection, symbol: str, meta: dict) -> int:
    """Resolve FOK/IOC/RETURN from the symbol's filling mode flags."""
    mode = meta.get("filling_mode")
    if mode is None:
        with contextlib.suppress(Exception):
            props = await conn.gateway.call("symbol_properties", symbol=symbol)
            mode = (props or {}).get("filling_mode")
    # SYMBOL_FILLING_FOK = 1, IOC = 2 (bit flags)
    if mode and int(mode) & 1:
        return 0  # ORDER_FILLING_FOK
    if mode and int(mode) & 2:
        return 1  # ORDER_FILLING_IOC
    return 2  # ORDER_FILLING_RETURN


async def close_position(ticket: int, volume: float | None = None, account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    result = await conn.gateway.close_position(ticket, volume)
    data.log_audit("position.close", f"ticket {ticket} vol {volume or 'all'}")
    hub.trade_events.publish({"ts": now(), "type": "close", "ticket": ticket, "volume": volume})
    return result


async def modify_position(ticket: int, sl: float | None, tp: float | None, account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    result = await conn.gateway.modify_position(ticket, sl, tp)
    data.log_audit("position.modify", f"ticket {ticket} sl={sl} tp={tp}")
    return result


async def delete_order(ticket: int, account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready()
    result = await conn.gateway.remove_order(ticket)
    data.log_audit("order.remove", f"ticket {ticket}")
    return result


async def disconnect(account_id: str | None = None) -> None:
    conn = connection(account_id)
    with contextlib.suppress(Exception):
        await conn.gateway.call("shutdown")
    conn.status = "disconnected"
    conn._inited_for = None
    await conn._update_account_status()


async def connect(account_id: str | None = None) -> dict:
    conn = connection(account_id)
    await conn.ensure_ready(force=True)
    return await conn.gateway.account_info()


# --------------------------------------------------------------------------- #
# lot sizing used by the algo engine + frontend calculator
# --------------------------------------------------------------------------- #


def estimate_lots(
    balance: float,
    risk_percent: float,
    stop_loss_points: float | None,
    symbol_meta: dict,
) -> float:
    """Risk-based lot sizing.

    ``lots * contract_size * point * stop_loss_points`` is the money at risk
    expressed in the symbol's profit currency; it is then converted to the
    account currency using the tick value when the terminal exposes it.
    """
    point = float(symbol_meta.get("point") or 1e-5)
    contract = float(symbol_meta.get("contract_size") or 0) or 100000.0
    if not balance or not stop_loss_points or not point:
        return 0.01
    risk_amount = balance * float(risk_percent) / 100.0
    loss_per_lot = contract * point * float(stop_loss_points)
    if loss_per_lot <= 0:
        return 0.01
    lots = risk_amount / loss_per_lot
    step = float(symbol_meta.get("volume_step") or 0.01)
    minimum = float(symbol_meta.get("volume_min") or 0.01)
    maximum = float(symbol_meta.get("volume_max") or 100.0)
    return round_to_step(min(lots, maximum), step, minimum, maximum)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x)) if math.isfinite(x) else lo
