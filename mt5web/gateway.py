"""MT5 access layer.

Two transports implement the same async gateway interface:

* ``InProcessGateway`` -- uses the ``MetaTrader5`` python package directly.
  Works **only on Windows** where the terminal is installed (a Render Linux
  service cannot host it: MetaQuotes ships Windows-only wheels).
* ``AgentGateway`` -- forwards RPC calls over an authenticated WebSocket to the
  bundled Bridge agent running on the Windows machine that hosts MetaTrader 5.

``get_gateway`` picks whichever live connection is configured, so the rest of
the app never needs to know where the terminal actually runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import struct
import time
from typing import Any

log = logging.getLogger("mt5web.gateway")


class GatewayError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}

# MetaTrader5.TIMEFRAME_* enum values (used for in-process calls and by the mock broker)
TIMEFRAME_CONST = {"M1": 1, "M5": 2, "M15": 3, "M30": 4, "H1": 5, "H4": 6, "D1": 7, "W1": 8}

ERR_HINTS = {
    -10004: "The 'MetaTrader5' python package is not available on this OS (Windows-only package).",
    -10005: "Bridge agent is not connected. Run agents\\start-agent.bat on the Windows machine.",
    -10006: "Terminal path not found on the agent machine.",
    -10007: "Trading is blocked by the Kill Switch in Settings.",
    -10008: "No MT5 account configured. Add Login / Password / Server under Accounts.",
    -10009: "Agent returned an oversized or malformed reply.",
    10000: "No connection to the trade server.",
    10001: "Application error in the terminal.",
    10002: "Wrong parameters in the trade request.",
    10003: "Request is too frequent.",
    10004: "Market is closed.",
    10005: "Order has already been placed (duplicate request).",
    10006: "Server is busy - the request was not processed, retry.",
    10007: "No changes were requested.",
    10008: "Order or position does not exist any more.",
    10009: "Done - the order was accepted.",
    10010: "Only part of the volume was executed.",
    10011: "Only part of the volume was executed and the rest was cancelled.",
    10012: "Request was cancelled by the trader.",
    10013: "Invalid request parameters.",
    10014: "Invalid volume (check min / max / step for the symbol).",
    10015: "Invalid or missing price.",
    10016: "Invalid stops - the distance to market is below the symbol freeze level.",
    10017: "Rejected - too many requests.",
    10018: "A price is required for this order type.",
    10019: "Volume is missing or invalid.",
    10020: "Trading is disabled for this account (check the broker/client settings).",
    10021: "No connection to the trade server.",
    10022: "Request was cancelled by the terminal.",
    10023: "Request was rejected because it would exceed the account's allowed state.",
    10024: "Too many requests.",
    10025: "Requests rate limit reached.",
    10026: "Requests executed with an error.",
    10027: "Trading is disabled by the terminal settings ('Algo trading' button).",
    10028: "Trading is disabled by the broker.",
    10029: "Price changed - requote.",
    10030: "Invalid expiration for a pending order.",
    10031: "State of the order is unknown - DO NOT retry blindly, check open positions first.",
    10032: "Spread has exceeded the allowed value.",
    10033: "Market prices are currently unavailable for the symbol.",
    10034: "Invalid balance or margin - not enough money to place this order.",
    10035: "Order state is unknown because the terminal was restarted.",
    10036: "Deals and orders history for the requested range is already available.",
    10038: "Positions and orders limit reached for the account.",
    10039: "Close request rejected because the volume exceeds the position.",
    10040: "Pending activation of an order was rejected by the broker.",
    10041: "Request was accepted but there is nothing to do.",
    10043: "Prices are not ready yet, try again in a moment.",
}


def err_text(retcode: int | None, fallback: str = "") -> str:
    if retcode in ERR_HINTS:
        return ERR_HINTS[retcode]
    return fallback or (f"Trade request failed (retcode {retcode})." if retcode else "Unknown error")


def normalize_symbol_info(symbol: str, info: dict | None) -> dict:
    info = info or {}
    digits = int(info.get("digits") or 5)
    point = float(info.get("point") or 0) or 10**-digits
    return {
        "name": symbol,
        "description": info.get("description"),
        "currency_profit": info.get("currency_profit"),
        "currency_margin": info.get("currency_margin"),
        "digits": digits,
        "point": point,
        "spread": int(info.get("spread") or 0),
        "bid": float(info.get("bid") or 0) or None,
        "ask": float(info.get("ask") or 0) or None,
        "volume_min": float(info.get("volume_min") or 0) or None,
        "volume_max": float(info.get("volume_max") or 0) or None,
        "volume_step": float(info.get("volume_step") or 0) or None,
        "tradeable": bool(info.get("tradeable", True)),
        "margin_initial": float(info.get("margin_initial") or 0) or None,
        "contract_size": float(info.get("trade_contract_size") or 0) or None,
        "filling_mode": int(info.get("filling_mode") or 0) or None,
    }


def round_to_step(volume: float, step: float | None = None, minimum: float | None = None, maximum: float | None = None) -> float:
    if step and step > 0:
        volume = round(round(volume / step) * step, 8)
    else:
        volume = round(volume, 8)
    if minimum and volume < minimum:
        volume = minimum
    if maximum and volume > maximum:
        volume = maximum
    return float(f"{volume:.8f}".rstrip("0").rstrip("."))


def account_info_to_dict(raw: dict | None) -> dict:
    """Normalised ACCOUNT_INFO. inf/nan margin levels become None (json-safe)."""
    raw = raw or {}
    out = {}
    for key, cast in {
        "login": int,
        "server": str,
        "currency": str,
        "balance": float,
        "equity": float,
        "margin": float,
        "margin_free": float,
        "margin_level": float,
        "credit": float,
        "profit": float,
        "leverage": int,
        "company": str,
    }.items():
        value = raw.get(key)
        if value in (None, ""):
            out[key] = None
            continue
        try:
            converted = cast(value)
        except (TypeError, ValueError):
            converted = None
        if isinstance(converted, float) and (math.isinf(converted) or math.isnan(converted)):
            converted = None
        out[key] = converted
    return out


def position_to_dict(row: dict, digits_map: dict[str, int] | None = None) -> dict:
    row = public_dict(row)
    symbol = row.get("symbol") or ""
    return {
        "ticket": int(row.get("ticket", 0) or 0),
        "order": int(row.get("order", 0) or 0),
        "time": int(row.get("time", 0) or 0),
        "type": "buy" if int(row.get("type", 0) or 0) == 0 else "sell",
        "symbol": symbol,
        "price_open": float(row.get("price_open", 0) or 0),
        "price_current": float(row.get("price_current", 0) or 0),
        "sl": float(row.get("sl", 0) or 0),
        "tp": float(row.get("tp", 0) or 0),
        "volume": float(row.get("volume", 0) or 0),
        "profit": float(row.get("profit", 0) or 0),
        "swap": float(row.get("swap", 0) or 0),
        "commission": float(row.get("commission", 0) or 0),
        "magic": int(row.get("magic", 0) or 0),
        "comment": row.get("comment") or "",
        "digits": (digits_map or {}).get(symbol, 5),
    }


def order_to_dict(row: dict) -> dict:
    row = public_dict(row)
    return {
        "ticket": int(row.get("ticket", 0) or 0),
        "symbol": row.get("symbol"),
        "type": int(row.get("type", 0) or 0),
        "type_text": str(row.get("type_text") or _ORDER_TYPES.get(int(row.get("type", 0) or 0), "")),
        "state": str(row.get("state_text") or ""),
        "time_setup": int(row.get("time_setup", 0) or 0),
        "price_open": float(row.get("price_open", 0) or 0),
        "sl": float(row.get("sl", 0) or 0),
        "tp": float(row.get("tp", 0) or 0),
        "price_current": float(row.get("price_current", 0) or 0),
        "type_filling": int(row.get("type_filling", 0) or 0),
        "magic": int(row.get("magic", 0) or 0),
        "comment": row.get("comment") or "",
    }


_ORDER_TYPES = {
    0: "buy",
    1: "sell",
    2: "buy_limit",
    3: "sell_limit",
    4: "buy_stop",
    5: "sell_stop",
}


def deal_to_dict(row: dict) -> dict:
    row = public_dict(row)
    entry = int(row.get("entry", 0) or 0)
    return {
        "ticket": int(row.get("ticket", 0) or 0),
        "order": int(row.get("order", 0) or 0),
        "time": int(row.get("time", 0) or 0),
        "type": "buy" if int(row.get("type", 0) or 0) == 0 else "sell",
        "entry": {0: "in", 1: "out", 2: "inout"}.get(entry, "in"),
        "magic": int(row.get("magic", 0) or 0),
        "profit": float(row.get("profit", 0) or 0),
        "swap": float(row.get("swap", 0) or 0),
        "commission": float(row.get("commission", 0) or 0),
        "fee": float(row.get("fee", 0) or 0),
        "price": float(row.get("price", 0) or 0),
        "volume": float(row.get("volume", 0) or 0),
        "position_id": int(row.get("position", 0) or 0),
        "symbol": row.get("symbol"),
        "comment": row.get("comment") or "",
    }


def rates_to_rows(raw: Any) -> list[dict]:
    """Convert MT5 rates (numpy structured array or list of dicts) into plain rows."""
    if raw is None:
        return []
    rows: list[dict] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                rows.append(
                    {
                        "time": int(item.get("time", 0) or 0),
                        "open": float(item.get("open", 0) or 0),
                        "high": float(item.get("high", 0) or 0),
                        "low": float(item.get("low", 0) or 0),
                        "close": float(item.get("close", 0) or 0),
                        "tick_volume": int(item.get("tick_volume", 0) or 0),
                    }
                )
            else:
                rows.append(
                    {
                        "time": int(item[0]),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "tick_volume": int(item[5]) if len(item) > 5 else 0,
                    }
                )
        return rows
    for rec in raw:  # numpy recarray
        rows.append(
            {
                "time": int(rec["time"]),
                "open": float(rec["open"]),
                "high": float(rec["high"]),
                "low": float(rec["low"]),
                "close": float(rec["close"]),
                "tick_volume": int(rec["tick_volume"]),
            }
        )
    return rows


def public_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if not str(k).startswith("_")}
    return {}


def unwrap(value: Any) -> Any:
    """Recursively convert MT5 namedtuples / numpy objects into JSON-able data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, struct.Struct):
        return None
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items() if not str(k).startswith("_")}
    if hasattr(value, "_asdict") and callable(getattr(value, "_asdict")):  # namedtuple *before* the tuple branch
        return {k: unwrap(v) for k, v in value._asdict().items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [unwrap(v) for v in value]
    if hasattr(value, "dtype") and hasattr(value, "__len__"):  # numpy array
        return [unwrap(v) for v in list(value)]
    if hasattr(value, "__dict__"):
        return {k: unwrap(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


# --------------------------------------------------------------------------- #
# base gateway
# --------------------------------------------------------------------------- #


class BaseGateway:
    live = True
    source = "unknown"
    supports_terminal_files = False

    async def call(self, method: str, **kwargs) -> Any:  # pragma: no cover - interface
        raise NotImplementedError("gateway transports must implement call()")

    async def close(self) -> None:
        return None

    # ---- read-only ---------------------------------------------------- #
    async def terminal_info(self) -> dict:
        return public_dict(await self.call("terminal_info"))

    async def account_info(self) -> dict:
        return account_info_to_dict(public_dict(await self.call("account_info")))

    async def symbols_total(self) -> list[str]:
        return list(await self.call("symbols_total") or [])

    async def symbol_info(self, symbol: str) -> dict:
        return normalize_symbol_info(symbol, public_dict(await self.call("symbol_info", symbol=symbol)))

    async def select(self, symbol: str, enable: bool = True) -> None:
        await self.call("symbol_select", symbol=symbol, select=enable)

    async def ticks(self, symbols: list[str]) -> dict[str, dict]:
        rows = await self.call("ticks_last", symbols=list(symbols), count=1) or {}
        if not rows:  # some builds prefer ticks_history; keep one clean fallback
            rows = {}
        out: dict[str, dict] = {}
        for symbol, rec in rows.items():
            if isinstance(rec, (list, tuple)):
                rec = rec[0] if rec else None
            rec = public_dict(rec)
            if not rec:
                continue
            bid = float(rec.get("bid", 0) or 0)
            ask = float(rec.get("ask", 0) or 0)
            last = float(rec.get("last", 0) or 0)
            out[symbol] = {
                "symbol": symbol,
                "time": float(rec.get("time", 0) or 0),
                "bid": bid,
                "ask": ask,
                "last": last,
                "mid": round((bid + ask) / 2, 8) if bid and ask else last,
            }
        return out

    async def rates(self, symbol: str, timeframe: str, count: int = 300) -> list[dict]:
        """copy_rates_from_pos(symbol, timeframe, start_position, count) - the real MT5 signature."""
        count = max(10, int(count))
        tf = TIMEFRAME_CONST.get(str(timeframe).upper(), 2)
        rows = await self.call(
            "copy_rates_from_pos", symbol=symbol, timeframe=tf, start_position=0, count=count
        )
        return rates_to_rows(rows)

    async def positions(self, symbol: str | None = None) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol
        rows = await self.call("positions_get", **kwargs) or []
        return [row for row in rows]

    async def orders(self) -> list[dict]:
        return list(await self.call("orders_get") or [])

    async def history_deals(self, from_ts: float, to_ts: float) -> list[dict]:
        rows = await self.call("history_deals_get", date_from=int(from_ts), date_to=int(to_ts)) or []
        return list(rows)

    async def last_error(self) -> tuple[int, str]:
        code, text = await self.call("last_error")
        return int(code or 0), str(text or "")

    # ---- trading ------------------------------------------------------ #
    async def place(self, req: dict) -> dict:
        """order_send with retcode interpretation."""
        result = public_dict(await self.call("order_send", request=req))
        retcode = int(result.get("retcode", 0) or 0)
        if retcode != 10009:
            code, text = await self.last_error()
            raise GatewayError(
                err_text(retcode, text),
                code=retcode or code or None,
                retryable=retcode in (10006, 10024, 10025, 10029),
            )
        result.setdefault("position", result.get("order") or result.get("deal") or 0)
        return result

    async def close_position(self, ticket: int, volume: float | None = None) -> dict:
        positions = [position_to_dict(p) for p in await self.positions()]
        pos = next((p for p in positions if p["ticket"] == ticket), None)
        if not pos:
            raise GatewayError(f"Position {ticket} not found on this account")
        partial = volume is not None and volume + 1e-12 < pos["volume"]
        if volume is not None and volume > pos["volume"] + 1e-12:
            raise GatewayError(f"Requested volume {volume} exceeds position volume {pos['volume']}")
        vol = round_to_step(volume if partial else pos["volume"])
        close_type = 1 if pos["type"] == "buy" else 0
        req = {
            "action": 1,  # TRADE_ACTION_DEAL
            "symbol": pos["symbol"],
            "volume": vol,
            "type": close_type,
            "type_filling": 0,
            "deviation": 20,
            "position": ticket,
            "comment": "web-close",
        }
        result = await self.place(req)
        result["partial"] = partial
        return result

    async def modify_position(self, ticket: int, sl: float | None, tp: float | None) -> dict:
        positions = [position_to_dict(p) for p in await self.positions()]
        pos = next((p for p in positions if p["ticket"] == ticket), None)
        if not pos:
            raise GatewayError(f"Position {ticket} not found on this account")
        req = {
            "action": 2,  # TRADE_ACTION_SLTP
            "symbol": pos["symbol"],
            "volume": pos["volume"],
            "position": ticket,
            "sl": sl if sl else 0.0,
            "tp": tp if tp else 0.0,
        }
        return await self.place(req)

    async def remove_order(self, ticket: int) -> dict:
        """TRADE_ACTION_REMOVE - some builds want symbol/volume echoed back, so we do."""
        req: dict[str, Any] = {"action": 4, "order": ticket}
        with contextlib.suppress(Exception):
            rows = [order_to_dict(o) for o in await self.orders()]
            row = next((o for o in rows if o["ticket"] == ticket), None)
            if row:
                req["symbol"] = row["symbol"]
                req["volume"] = row.get("volume_current") or row.get("volume") or 0.0
        return await self.place(req)


# --------------------------------------------------------------------------- #
# in-process (Windows) gateway
# --------------------------------------------------------------------------- #


class InProcessGateway(BaseGateway):
    source = "local"
    supports_terminal_files = True

    def __init__(self) -> None:
        self._mt5 = None

    def load(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except Exception as exc:  # pragma: no cover - expected on Linux
                raise GatewayError(
                    "MetaTrader5 python package unavailable here "
                    f"({exc.__class__.__name__}: {exc}). The package ships Windows-only "
                    "wheels - start the Bridge agent on the Windows machine instead.",
                    code=-10004,
                ) from exc
            self._mt5 = mt5
        return self._mt5

    async def call(self, method: str, params: dict | None = None, **kwargs) -> Any:
        mt5 = self.load()
        fn = getattr(mt5, method, None)
        if fn is None:
            raise GatewayError(f"MetaTrader5.{method}() is not available in this terminal build")
        merged = dict(params or {})
        merged.update(kwargs)
        clean = {k: v for k, v in merged.items() if v is not None}
        return unwrap(await asyncio.to_thread(lambda: fn(**clean)))

    async def initialize_terminal(self, kwargs: dict) -> bool:
        mt5 = self.load()
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return bool(await asyncio.to_thread(lambda: mt5.initialize(**clean)))

    async def shutdown(self) -> None:
        if self._mt5 is not None:
            await asyncio.to_thread(self._mt5.shutdown)

    async def rates(self, symbol: str, timeframe: str, count: int = 300) -> list[dict]:
        mt5 = self.load()
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", 2)
        rows = await asyncio.to_thread(
            lambda: mt5.copy_rates_from_pos(symbol, tf, 0, max(10, int(count)))
        )
        return rates_to_rows(rows)
