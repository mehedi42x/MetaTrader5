"""A simulated MetaTrader 5 broker + a bridge-agent emulator.

This is what lets you develop and demo the whole web app on Linux (or on any
machine without MetaTrader installed): it speaks the *exact* protocol of
``agents/agent/main.py`` but answers from an in-process market simulator.

    python agents/mock_agent.py --url ws://127.0.0.1:8000/ws/agent --key <key>

Never point this at a real account - it is a toy broker for UI/logic testing.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import platform
import random
import time
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover
    print("pip install websockets first")
    raise

HERE = Path(__file__).resolve().parent
DATA = HERE / ".mock_mt5_data"
INSTALL = DATA / "terminal"
INSTALL.mkdir(parents=True, exist_ok=True)
(INSTALL / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
(INSTALL / "MQL5" / "Files").mkdir(parents=True, exist_ok=True)
(INSTALL / "MQL5" / "Logs").mkdir(parents=True, exist_ok=True)
(INSTALL / "Logs").mkdir(parents=True, exist_ok=True)
(INSTALL / "metaeditor64.exe").write_bytes(b"MZ mock")

BAR_SECONDS = 60  # 1-minute base bars; other timeframes are aggregated

SYMBOLS: dict[str, dict] = {
    "EURUSD": {"digits": 5, "point": 1e-5, "base": 1.0850, "sigma": 0.00012, "spread_pts": 8, "contract": 100000, "tick_value": 1.0, "tick_size": 1e-5, "vmin": 0.01, "vmax": 50, "vstep": 0.01, "desc": "Euro vs US Dollar"},
    "GBPUSD": {"digits": 5, "point": 1e-5, "base": 1.2650, "sigma": 0.00015, "spread_pts": 12, "contract": 100000, "tick_value": 1.0, "tick_size": 1e-5, "vmin": 0.01, "vmax": 50, "vstep": 0.01, "desc": "Great Britain Pound vs US Dollar"},
    "USDJPY": {"digits": 3, "point": 0.001, "base": 148.20, "sigma": 0.018, "spread_pts": 11, "contract": 100000, "tick_value": 0.67, "tick_size": 0.001, "vmin": 0.01, "vmax": 50, "vstep": 0.01, "desc": "US Dollar vs Japanese Yen"},
    "AUDUSD": {"digits": 5, "point": 1e-5, "base": 0.6620, "sigma": 0.00009, "spread_pts": 10, "contract": 100000, "tick_value": 1.0, "tick_size": 1e-5, "vmin": 0.01, "vmax": 50, "vstep": 0.01, "desc": "Australian Dollar vs US Dollar"},
    "USDCAD": {"digits": 5, "point": 1e-5, "base": 1.3710, "sigma": 0.00010, "spread_pts": 14, "contract": 100000, "tick_value": 0.73, "tick_size": 1e-5, "vmin": 0.01, "vmax": 50, "vstep": 0.01, "desc": "US Dollar vs Canadian Dollar"},
    "XAUUSD": {"digits": 2, "point": 0.01, "base": 2465.0, "sigma": 0.55, "spread_pts": 250, "contract": 100, "tick_value": 1.0, "tick_size": 0.01, "vmin": 0.01, "vmax": 100, "vstep": 0.01, "desc": "Gold vs US Dollar"},
    "BTCUSD": {"digits": 2, "point": 0.01, "base": 61500.0, "sigma": 22.0, "spread_pts": 3000, "contract": 1, "tick_value": 1.0, "tick_size": 0.01, "vmin": 0.001, "vmax": 5, "vstep": 0.001, "desc": "Bitcoin vs US Dollar"},
    "ETHUSD": {"digits": 2, "point": 0.01, "base": 2980.0, "sigma": 2.2, "spread_pts": 900, "contract": 1, "tick_value": 1.0, "tick_size": 0.01, "vmin": 0.01, "vmax": 100, "vstep": 0.01, "desc": "Ethereum vs US Dollar"},
}

TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}


class MarketSim:
    """Deterministic random-walk market with 1-minute history + open trades."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed if seed is not None else 20260917)
        self.started = int(time.time() // BAR_SECONDS * BAR_SECONDS) - BAR_SECONDS * 6000
        self.history: dict[str, list[dict]] = {}
        self.walk: dict[str, list[float]] = {s: [] for s in SYMBOLS}
        for symbol, cfg in SYMBOLS.items():
            price = cfg["base"]
            for _ in range(6000):
                step = self.rng.gauss(0.0, cfg["sigma"]) + cfg["sigma"] * 0.05 * math.sin(time.time() / 5000 + price)
                price = max(price + step, cfg["base"] * 0.2)
                self.walk[symbol].append(price)
        self.balance = 10_000.0
        self.positions: dict[int, dict] = {}
        self.orders: dict[int, dict] = {}
        self.deals: list[dict] = []
        self._next_ticket = 100_000
        self.login = 0
        self.server = ""
        self.algo_trading = True

    # ---- prices ------------------------------------------------------- #
    def current(self, symbol: str) -> float:
        cfg = SYMBOLS.get(symbol)
        if not cfg:
            return 0.0
        walk = self.walk[symbol]
        elapsed = time.time() - self.started
        idx = int(elapsed // BAR_SECONDS) % max(1, len(walk))
        drift = 0.4 * cfg["sigma"] * math.sin(elapsed / 240.0) + 0.25 * cfg["sigma"] * math.sin(elapsed / 77.0)
        return walk[idx] + drift

    def bar(self, symbol: str, index: int, seconds: int) -> dict:
        cfg = SYMBOLS[symbol]
        step_seconds = seconds
        start = int((time.time() - step_seconds * (index + 1)) // step_seconds * step_seconds)
        end = start + step_seconds
        samples: list[float] = []
        t = start
        while t < end:
            samples.append(self.price_at(symbol, t))
            t += BAR_SECONDS / 4
        if not samples:
            samples = [self.current(symbol)]
        o = samples[0]
        c = samples[-1]
        return {
            "time": start,
            "open": round(o, cfg["digits"]),
            "high": round(max(samples + [o, c]), cfg["digits"]),
            "low": round(min(samples + [o, c]), cfg["digits"]),
            "close": round(c, cfg["digits"]),
            "tick_volume": int(max(5, abs(c - o) / cfg["sigma"] * 25)),
            "spread": cfg["spread_pts"],
            "real_volume": int(max(1, (max(samples) - min(samples)) / cfg["sigma"])) * 12,
        }

    def price_at(self, symbol: str, ts: float) -> float:
        cfg = SYMBOLS[symbol]
        walk = self.walk[symbol]
        idx = int((ts - self.started) // BAR_SECONDS) % len(walk)
        return walk[idx] + 0.35 * cfg["sigma"] * math.sin(ts / 300.0)

    def bars(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        seconds = TIMEFRAME_SECONDS.get(timeframe.upper(), 300)
        rows = [self.bar(symbol, i, seconds) for i in range(count)]
        rows.sort(key=lambda r: r["time"])
        return rows

    # ---- trading ------------------------------------------------------ #
    def new_ticket(self) -> int:
        self._next_ticket += 1
        return self._next_ticket

    def floating(self, pos: dict) -> float:
        cfg = SYMBOLS[pos["symbol"]]
        price = self.current(pos["symbol"])
        direction = 1 if pos["type"] == 0 else -1
        return direction * (price - pos["price_open"]) / cfg["tick_size"] * cfg["tick_value"] * pos["volume"]

    def equity(self) -> float:
        return self.balance + sum(self.floating(p) for p in self.positions.values())

    def margin(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            cfg = SYMBOLS[pos["symbol"]]
            total += pos["volume"] * (cfg["contract"] * self.current(pos["symbol"])) / 100.0
        return round(total, 2)

    def refresh(self) -> None:
        """Evaluate SL / TP and pending orders against the simulated prices."""
        for ticket in list(self.positions):
            pos = self.positions[ticket]
            price = self.current(pos["symbol"])
            closed = None
            if pos["type"] == 0:
                if pos["sl"] and price <= pos["sl"]:
                    closed = pos["sl"]
                elif pos["tp"] and price >= pos["tp"]:
                    closed = pos["tp"]
            else:
                if pos["sl"] and price >= pos["sl"]:
                    closed = pos["sl"]
                elif pos["tp"] and price <= pos["tp"]:
                    closed = pos["tp"]
            if closed is not None:
                self._close(ticket, closed, "SL/TP")
        for ticket in list(self.orders):
            order = self.orders[ticket]
            price = self.current(order["symbol"])
            trigger = None
            if order["type"] == 2 and price <= order["price_open"]:
                trigger = price
            elif order["type"] == 3 and price >= order["price_open"]:
                trigger = price
            elif order["type"] == 4 and price >= order["price_open"]:
                trigger = price
            elif order["type"] == 5 and price <= order["price_open"]:
                trigger = price
            if trigger is not None:
                self.orders.pop(ticket)
                self._open(trigger, order, "pending activated")

    def _open(self, price: float, req: dict, comment: str) -> dict:
        ticket = self.new_ticket()
        pos = {
            "ticket": ticket,
            "order": ticket,
            "time": int(time.time()),
            "type": req["type"],
            "magic": int(req.get("magic") or 0),
            "symbol": req["symbol"],
            "volume": float(req["volume"]),
            "price_open": round(price, SYMBOLS[req["symbol"]]["digits"]),
            "sl": float(req.get("sl") or 0),
            "tp": float(req.get("tp") or 0),
            "swap": 0.0,
            "profit": 0.0,
            "commission": -0.02 * float(req["volume"]) * 100,
            "comment": req.get("comment") or comment,
            "time_msc": int(time.time() * 1000),
        }
        self.positions[ticket] = pos
        self.deals.append(
            {
                "ticket": self.new_ticket(),
                "order": ticket,
                "time": int(time.time()),
                "type": req["type"],
                "entry": 0,
                "magic": pos["magic"],
                "profit": 0.0,
                "swap": 0.0,
                "commission": pos["commission"],
                "fee": 0.0,
                "price": pos["price_open"],
                "volume": pos["volume"],
                "position": ticket,
                "symbol": pos["symbol"],
                "comment": pos["comment"],
            }
        )
        return {"retcode": 10009, "order": ticket, "deal": self.deals[-1]["ticket"], "price": pos["price_open"], "volume": pos["volume"], "comment": "mock ok"}

    def _close(self, ticket: int, price: float, reason: str) -> dict:
        pos = self.positions.pop(ticket, None)
        if pos is None:
            return {"retcode": 10008, "comment": "position not found"}
        cfg = SYMBOLS[pos["symbol"]]
        direction = 1 if pos["type"] == 0 else -1
        profit = direction * (price - pos["price_open"]) / cfg["tick_size"] * cfg["tick_value"] * pos["volume"]
        self.balance = round(self.balance + profit + pos.get("commission", 0), 2)
        self.deals.append(
            {
                "ticket": self.new_ticket(),
                "order": pos["order"],
                "time": int(time.time()),
                "type": 1 if pos["type"] == 0 else 0,
                "entry": 1,
                "magic": pos["magic"],
                "profit": round(profit, 2),
                "swap": 0.0,
                "commission": 0.0,
                "fee": 0.0,
                "price": round(price, cfg["digits"]),
                "volume": pos["volume"],
                "position": ticket,
                "symbol": pos["symbol"],
                "comment": reason,
            }
        )
        return {"retcode": 10009, "order": ticket, "deal": self.deals[-1]["ticket"], "price": round(price, cfg["digits"]), "profit": round(profit, 2), "comment": reason}


SIM = MarketSim()


# --------------------------------------------------------------------------- #
# the "MetaTrader5" module facade
# --------------------------------------------------------------------------- #


class SimError(RuntimeError):
    pass


_last_error = (1, "Success")


def last_error() -> tuple[int, str]:
    return _last_error


def initialize(*, path: str | None = None, login: int | None = None, password: str = "", server: str = "", timeout: int = 60000, **_: object) -> bool:
    global _last_error
    time.sleep(0.05)
    if password.lower() in {"wrong", "bad", "0000"}:
        _last_error = (-5, "Invalid password")
        return False
    if login and int(login) <= 0:
        _last_error = (-4, "Invalid account")
        return False
    SIM.login = int(login or 1234567)
    SIM.server = server or "Mock-Demo01"
    _last_error = (1, "Success")
    return True


def shutdown() -> None:
    return None


def terminal_info() -> dict:
    return {
        "_path": "",
        "data_path": str(INSTALL),
        "commondata_path": str(INSTALL),
        "exe_path": str(INSTALL / "terminal64.exe"),
        "build": 4400,
        "connected": True,
        "community_account": True,
        "trade_allowed": SIM.algo_trading,
        "trade_api_allowed": True,
        "network_delay": 24,
        "terminal_external": True,
        "dlls_allowed": False,
        "auto_chat_enabled": False,
    }


def terminal_path() -> str:
    return str(INSTALL / "terminal64.exe")


def terminal_data_path() -> str:
    return str(INSTALL)


def account_info() -> dict:
    SIM.refresh()
    margin = SIM.margin()
    return {
        "login": SIM.login,
        "trade_server": SIM.server,
        "server": SIM.server,
        "currency": "USD",
        "balance": SIM.balance,
        "credit": 0.0,
        "profit": round(sum(SIM.floating(p) for p in SIM.positions.values()), 2),
        "equity": round(SIM.equity(), 2),
        "margin": margin,
        "margin_free": round(SIM.equity() - margin, 2),
        "margin_level": round(100 * SIM.equity() / margin, 2) if margin else float("inf"),
        "margin_so_call": 50.0,
        "margin_so_stop": 20.0,
        "leverage": 100,
        "company": "Mock Markets Ltd",
        "name": f"Mock demo {SIM.login}",
        "trade_mode": 1,
        "limit_orders": 200,
    }


def symbols_total() -> list[str]:
    return [{"name": name, "description": cfg["desc"]} for name, cfg in SYMBOLS.items()]


def symbol_info(symbol: str) -> dict | None:
    cfg = SYMBOLS.get(symbol)
    if not cfg:
        return None
    price = SIM.current(symbol)
    half = cfg["spread_pts"] * cfg["point"] / 2
    return {
        "symbol": symbol,
        "description": cfg["desc"],
        "export": True,
        "digits": cfg["digits"],
        "point": cfg["point"],
        "trade_tick_value": cfg["tick_value"],
        "trade_tick_size": cfg["tick_size"],
        "trade_contract_size": cfg["contract"],
        "currency_profit": "USD",
        "currency_margin": "USD",
        "bid": round(price - half, cfg["digits"]),
        "ask": round(price + half, cfg["digits"]),
        "last": round(price, cfg["digits"]),
        "volume_min": cfg["vmin"],
        "volume_max": cfg["vmax"],
        "volume_step": cfg["vstep"],
        "spread": cfg["spread_pts"],
        "trade_stops_level": 10,
        "trade_freeze_level": 5,
        "trade_exemode": 0,
        "trade_mode": 4,
        "trade_allowed": True,
        "visible": True,
        "selected": True,
        "filling_mode": 3,
    }


def symbol_select(symbol: str, select: bool = True) -> bool:
    return symbol in SYMBOLS


def symbols_get(group: str | None = None) -> list[dict]:
    return [s for s in symbols_total()] if group in (None, "*", "") else symbols_total()





def ticks_last(symbols: list[str] | None = None, count: int = 1) -> dict[str, list[dict]]:
    """Same shape as MetaTrader5.ticks_last(): {symbol: [tick, ...]} newest last."""
    names = [s.upper() for s in (symbols or list(SYMBOLS))]
    out: dict[str, list[dict]] = {}
    for symbol in names:
        info = symbol_info(symbol)
        if not info:
            continue
        stamp = time.time()
        out[symbol] = [
            {
                "time": stamp + n,
                "bid": info["bid"],
                "ask": info["ask"],
                "last": info["last"],
                "volume": 1 + n,
                "volume_real": 0.0,
                "flags": 0,
            }
            for n in range(max(1, int(count)))
        ]
    return out


def ticks_stock(symbols: list[str] | None = None, count: int = 1) -> dict[str, list[dict]]:
    # the mock has no tick history distinction - same source, documented
    return ticks_last(symbols, count)


def copy_rates_from_pos(symbol: str, timeframe, start_position: int = 0, count: int = 100) -> list[dict]:
    if symbol not in SYMBOLS:
        return []
    tf = timeframe if isinstance(timeframe, str) else _TF_NAMES.get(int(timeframe), "M5")
    rows = SIM.bars(symbol, tf, count + int(start_position or 0))
    return rows[int(start_position):] if start_position else rows


_TF_NAMES = {1: "M1", 2: "M5", 3: "M15", 4: "M30", 5: "H1", 6: "H4", 7: "D1", 8: "W1"}


def history_deals_get(date_from: int = 0, date_to: int = 0, group: str | None = None) -> list[dict]:
    SIM.refresh()
    rows = [d for d in SIM.deals if date_from <= d["time"] <= date_to] or list(SIM.deals)
    return rows


def positions_get(symbol: str | None = None, group: str | None = None) -> list[dict]:
    SIM.refresh()
    rows = []
    for pos in SIM.positions.values():
        if symbol and pos["symbol"] != symbol:
            continue
        row = dict(pos)
        row["price_current"] = round(SIM.current(pos["symbol"]), SYMBOLS[pos["symbol"]]["digits"])
        row["price_sl"] = pos["sl"]
        row["price_tp"] = pos["tp"]
        row["time_msc"] = pos["time"] * 1000
        row["identifier"] = pos["ticket"]
        row["external_id"] = ""
        row["state"] = 1
        row["type_time"] = 0
        row["type_filling"] = 0
        rows.append(row)
    return rows


def orders_get(symbol: str | None = None, group: str | None = None) -> list[dict]:
    rows = []
    for order in SIM.orders.values():
        if symbol and order["symbol"] != symbol:
            continue
        row = dict(order)
        row["type_text"] = {0: "buy", 1: "sell", 2: "buy limit", 3: "sell limit", 4: "buy stop", 5: "sell stop"}[order["type"]]
        row["state_text"] = "started"
        row["time_setup"] = order["time"]
        row["time_done"] = 0
        rows.append(row)
    return rows


def order_send(request: dict) -> dict:
    global _last_error
    SIM.refresh()
    _last_error = (1, "Success")  # never leak a stale code into last_error()
    action = int(request.get("action", 0))
    symbol = request.get("symbol", "")
    cfg = SYMBOLS.get(symbol)
    if cfg is None:
        _last_error = (10013, "Unknown symbol")
        return {"retcode": 10013, "error": "unknown symbol"}
    volume = float(request.get("volume") or 0)
    if action in (1, 3):  # DEAL / PENDING need a tradable volume; SLTP + REMOVE do not
        volume = round(round(volume / cfg["vstep"]) * cfg["vstep"], 8)
        if volume < cfg["vmin"] or volume > cfg["vmax"]:
            _last_error = (10014, "Invalid volume")
            return {"retcode": 10014, "volume": volume}
    price = float(request.get("price") or 0) or SIM.current(symbol)
    digits = cfg["digits"]
    if action == 1:  # DEAL
        ticket = int(request.get("position") or 0)
        if ticket:
            pos = SIM.positions.get(ticket)
            if pos is None:
                return {"retcode": 10008, "error": "position not found"}
            partial = volume + 1e-12 < pos["volume"]
            if partial:
                pos["volume"] = round(pos["volume"] - volume, 8)
                cfg_local = SYMBOLS[pos["symbol"]]
                direction = 1 if pos["type"] == 0 else -1
                profit = direction * (price - pos["price_open"]) / cfg_local["tick_size"] * cfg_local["tick_value"] * volume
                SIM.balance = round(SIM.balance + profit, 2)
                SIM.deals.append({
                    "ticket": SIM.new_ticket(), "order": ticket, "time": int(time.time()),
                    "type": 1 if pos["type"] == 0 else 0, "entry": 2, "magic": pos["magic"],
                    "profit": round(profit, 2), "swap": 0.0, "commission": 0.0, "fee": 0.0,
                    "price": round(price, cfg_local["digits"]), "volume": volume, "position": ticket,
                    "symbol": pos["symbol"], "comment": request.get("comment") or "partial",
                })
                return {"retcode": 10009, "order": SIM.new_ticket(), "deal": SIM.deals[-1]["ticket"], "price": round(price, cfg_local["digits"]), "profit": round(profit, 2), "partial": True}
            res = SIM._close(ticket, price, request.get("comment") or "close")  # noqa: SLF001
            _last_error = (1, "Success")
            return res
        otype = int(request.get("type", 0))
        if otype in (0, 1):
            res = SIM._open(price, {**request, "volume": volume}, "market")  # noqa: SLF001
            _last_error = (1, "Success")
            return res
        _last_error = (10002, "Wrong parameters")
        return {"retcode": 10002}
    if action == 2:  # SLTP
        ticket = int(request.get("position") or 0)
        pos = SIM.positions.get(ticket)
        if not pos:
            return {"retcode": 10008}
        pos["sl"] = round(float(request.get("sl") or 0), digits)
        pos["tp"] = round(float(request.get("tp") or 0), digits)
        return {"retcode": 10009, "order": ticket}
    if action == 3:  # PENDING ORDER
        otype = int(request.get("type", 0))
        if otype not in (2, 3, 4, 5, 6):
            _last_error = (10022, "Invalid request parameters (not a pending order type)")
            return {"retcode": 10022}
        if price <= 0:
            _last_error = (10022, "Invalid request parameters (price required for pending orders)")
            return {"retcode": 10022}
        spot = SIM.current(symbol)
        if otype in (2, 4) and abs(price - spot) < cfg["tick_size"]:
            _last_error = (10022, "Invalid request parameters (price too close to market)")
            return {"retcode": 10022}
        if otype in (3, 5) and abs(price - spot) < cfg["tick_size"]:
            _last_error = (10022, "Invalid request parameters (price too close to market)")
            return {"retcode": 10022}
        ticket = SIM.new_ticket()
        SIM.orders[ticket] = {
            "ticket": ticket,
            "symbol": symbol,
            "type": int(request.get("type", 2)),
            "state": 1,
            "time": int(time.time()),
            "time_setup": int(time.time()),
            "price_open": round(price, digits),
            "sl": round(float(request.get("sl") or 0), digits),
            "tp": round(float(request.get("tp") or 0), digits),
            "type_filling": int(request.get("type_filling") or 0),
            "magic": int(request.get("magic") or 0),
            "volume": volume,
            "volume_current": volume,
            "comment": request.get("comment") or "mock",
        }
        return {"retcode": 10009, "order": ticket}
    if action == 4:  # REMOVE pending order
        ticket = int(request.get("order") or 0)
        existed = SIM.orders.pop(ticket, None)
        return {"retcode": 10009 if existed else 10008, "order": ticket}
    _last_error = (10002, "unsupported action in mock")
    return {"retcode": 10002}


# --------------------------------------------------------------------------- #
# agent protocol emulation
# --------------------------------------------------------------------------- #


class MockAgent:
    def __init__(self, name: str, ws) -> None:
        self.ws = ws
        self.name = name
        self.seq = 0

    async def send(self, payload: dict) -> None:
        await self.ws.send(json.dumps(payload, default=str))

    async def handle(self, method: str, params: dict) -> Any:  # noqa: ANN401
        mod = globals()
        if method in ("fs_write", "fs_read", "fs_list", "fs_delete", "file_exists", "terminal_compile", "tail_logs", "prepare_ini", "mt5_status"):
            return await self._files(method, params)
        fn = mod.get(method)
        if fn is None or not callable(fn):
            raise RuntimeError(f"mock broker has no {method}()")
        clean = {k: v for k, v in params.items() if k not in ("account_id",) and v is not None}
        return unwrap(fn(**clean))

    # ---- file/compile emulation on the local disk ---------------------- #
    def _base(self, mode: str) -> Path:
        return {"filesandbox": INSTALL / "MQL5" / "Files", "data": INSTALL}.get(mode, INSTALL)

    async def _files(self, method: str, params: dict) -> Any:  # noqa: ANN401, C901
        raw = str(params.get("path") or "").lstrip("\\/")
        base = self._base(params.get("mode", "data"))
        target = Path(raw) if Path(raw).is_absolute() else (base / raw)
        target = target.resolve()
        if not str(target).startswith(str(base.resolve())):
            raise RuntimeError("path escapes the mock terminal folder")
        if method == "fs_write":
            target.parent.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(params["content"]) if params.get("b64") else str(params.get("content", "")).encode()
            target.write_bytes(data)
            return {"ok": True, "absolute": str(target), "bytes": len(data), "mtime": target.stat().st_mtime}
        if method == "fs_read":
            if not target.exists():
                return {"exists": False, "text": ""}
            return {"exists": True, "text": target.read_text(encoding="utf-8", errors="replace"), "mtime": target.stat().st_mtime}
        if method == "file_exists":
            return {"exists": target.exists(), "absolute": str(target), "size": target.stat().st_size if target.exists() else 0}
        if method == "fs_list":
            if not target.exists():
                return []
            return [{"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime, "dir": p.is_dir()} for p in sorted(target.iterdir())]
        if method == "fs_delete":
            existed = target.exists()
            if existed:
                target.unlink(missing_ok=True)
            return {"ok": True, "deleted": existed}
        if method == "terminal_compile":
            src = Path(params.get("path") or "")
            if not src.is_absolute():
                src = INSTALL / src
            log_path = src.with_suffix(".log")
            text = ""
            errors = 0
            if src.exists():
                body = src.read_text(encoding="utf-8", errors="replace")
                problems = []
                if "input " not in body:
                    problems.append("'input' declaration missing")
                if "OnTick" not in body:
                    problems.append("no OnTick() function found")
                if "#property" not in body:
                    problems.append("compilation log: no #property header")
                if "CTrade" in body and "#include <Trade/Trade.mqh>" not in body:
                    problems.append("'CTrade' - unexpected token")
                # deliberately crude global balance check (real MetaEditor is far stricter)
                if body.count("{") != body.count("}"):
                    problems.append(f"syntax error, unmatched brace (line {len(body.splitlines())})")
                if body.count("(") != body.count(")"):
                    problems.append("syntax error, unmatched parenthesis")
                if problems:
                    errors = len(problems)
                    text = "\n".join(f"{src.name}({i + 1},1) : error : {p}" for i, p in enumerate(problems))
                    text += f"\nResult: 0 warnings, {errors} errors, 0 ms elapsed, cpu='X64 Regular'"
                else:
                    ex5 = src.with_suffix(".ex5")
                    ex5.write_bytes(b"MOCKEX5" + body.encode()[:64])
                    text = f"compiled {src.name} successfully\nResult: 0 warnings, 0 errors, 43 ms elapsed, cpu='X64 Regular'"
                log_path.write_text(text, encoding="utf-8")
                target = src.with_suffix(".ex5")
            return {
                "ok": errors == 0 and bool(text),
                "returncode": 0,
                "log": str(log_path),
                "output": text,
                "errors": errors,
                "source": str(src),
                "ex5": str(src.with_suffix(".ex5")),
                "ex5_exists": src.with_suffix(".ex5").exists(),
            }
        if method == "prepare_ini":
            target = INSTALL / f"mt5web_{params.get('name', 'mock')}.ini"
            target.write_text(
                "[Common]\r\n"
                f"Login={params.get('login', 1234567)}\r\nPassword=mock\r\n"
                f"Server={params.get('server', 'Mock-Demo01')}\r\n\r\n[Experts]\r\nAllowLiveTrading=1\r\nEnabled=1\r\n",
                encoding="utf-8",
            )
            return {"ok": True, "ini": str(target), "start_command": f'"{INSTALL / "terminal64.exe"}" /config:"{target}"', "note": "mock"}
        if method == "tail_logs":
            lines = []
            for log_file in sorted((INSTALL / "MQL5" / "Logs").glob("*.log"))[-1:]:
                for line in log_file.read_text(errors="replace").splitlines()[-40:]:
                    lines.append({"file": log_file.name, "line": line})
            return {"lines": lines[-int(params.get("lines") or 100):], "at": time.time()}
        if method == "mt5_status":
            return {"package_installed": False, "terminal_path": str(INSTALL / "terminal64.exe"), "data_folder": str(INSTALL), "initialized": {"login": SIM.login, "server": SIM.server}, "version": "MOCK-5.0"}
        raise RuntimeError(f"unknown file method {method}")


def unwrap(value):
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [unwrap(v) for v in value]
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    return value


async def session(ws, name: str) -> None:
    agent = MockAgent(name, ws)
    hello = {
        "t": "hello",
        "name": name,
        "agent_version": "MOCK-1.0",
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.node(),
        "python": platform.python_version(),
        "mt5_available": True,
        "mt5_version": "5.0.4400 (mock)",
        "terminal_path": str(INSTALL / "terminal64.exe"),
        "data_folder": str(INSTALL),
        "initialized": None,
    }
    await agent.send(hello)
    welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    print(f"[mock] welcome: {welcome}")
    last_tail = 0.0
    async for raw in ws:
        msg = json.loads(raw)
        if msg.get("t") != "rpc":
            if msg.get("action") == "tail":
                await agent.send({"t": "event", "event": "log", "payload": await agent._files("tail_logs", msg.get("params") or {})})
            continue
        rid = msg.get("id")
        try:
            result = await agent.handle(msg.get("method", ""), msg.get("params") or {})
            await agent.send({"t": "rpc_result", "id": rid, "result": unwrap(result)})
        except Exception as exc:  # noqa: BLE001
            await agent.send({"t": "rpc_error", "id": rid, "error": f"{exc.__class__.__name__}: {exc}"})
        if time.time() - last_tail > 5:
            last_tail = time.time()


async def main_loop(url: str, key: str, name: str) -> None:
    backoff = 2
    while True:
        try:
            async with websockets.connect(f"{url}?key={key}", ping_interval=20, max_size=40_000_000) as ws:
                print(f"[mock] connected to {url}")
                backoff = 2
                await session(ws, name)
        except Exception as exc:  # noqa: BLE001
            print(f"[mock] connection lost: {exc} (retry in {backoff}s)")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("MT5WEB_URL", "ws://127.0.0.1:8000/ws/agent"))
    parser.add_argument("--key", default=os.getenv("MT5WEB_KEY", ""))
    parser.add_argument("--name", default="mock-terminator")
    args = parser.parse_args()
    asyncio.run(main_loop(args.url, args.key, args.name))
