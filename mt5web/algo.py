"""Algo engine: user Python strategies, live execution and MQL5 EA deployment.

Strategy contract (the whole point of "Algo Studio")::

    def init(ctx):
        ctx.p.setdefault("fast", 12)      # user-editable params live in ctx.p

    def on_bar(ctx, bars, i):
        if ctx.ready < i + 1:
            return None                    # not enough history yet
        if bars.macd_cross_up(i):
            ctx.log("MACD cross up -> buy")
            return {"action": "buy", "volume": ctx.volume}
        return None

``on_bar`` returns ``None`` (nothing), ``{"action": "buy"|"sell"|"close", ...}``
or the shorthands ``1 / -1 / 0``.  Signals are executed live through the same
code path the dashboard uses, so every order goes through the risk guards.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
import traceback
from typing import Any, Callable

from . import MQL5, broker, market
from .backtest import run_backtest
from .config import settings
from .gateway import GatewayError, round_to_step
from .hub import hub
from .store import data, new_id, now

log = logging.getLogger("mt5web.algo")

MAX_LOG_ROWS = 800
LOG_FILES: dict[str, list[dict]] = {}


# --------------------------------------------------------------------------- #
# bars helper passed to the strategy
# --------------------------------------------------------------------------- #


class Bars:
    """Read-only candle accessor with a few built-in indicators."""

    def __init__(self, rows: list[dict], meta: dict | None = None) -> None:
        self.rows = rows
        self.meta = meta or {}
        self.point = float(self.meta.get("point") or 1e-5)
        self.digits = int(self.meta.get("digits") or 5)
        self._o = [r["open"] for r in rows]
        self._h = [r["high"] for r in rows]
        self._l = [r["low"] for r in rows]
        self._c = [r["close"] for r in rows]
        self._v = [r.get("tick_volume", 0) for r in rows]
        self._t = [r["time"] for r in rows]

    # ---- raw access ------------------------------------------------- #
    def __len__(self) -> int:
        return len(self.rows)

    @property
    def open(self) -> list[float]:
        return self._o

    @property
    def high(self) -> list[float]:
        return self._h

    @property
    def low(self) -> list[float]:
        return self._l

    @property
    def close(self) -> list[float]:
        return self._c

    @property
    def volume(self) -> list[int]:
        return self._v

    @property
    def time(self) -> list[int]:
        return self._t

    def price_points(self, index: int) -> float:
        return self._c[index] / self.point

    def atr_points(self, index: int, period: int = 14) -> float:
        trs = []
        for k in range(max(1, index - period + 1), index + 1):
            tr = max(
                self._h[k] - self._l[k],
                abs(self._h[k] - self._c[k - 1]),
                abs(self._l[k] - self._c[k - 1]),
            )
            trs.append(tr / self.point)
        return sum(trs) / len(trs) if trs else 0.0

    # ---- indicators --------------------------------------------------- #
    def sma(self, period: int, index: int | None = None, series: list[float] | None = None) -> float:
        series = series or self._c
        end = len(series) if index is None else index + 1
        window = series[max(0, end - period) : end]
        return sum(window) / len(window) if window else 0.0

    def ema_series(self, period: int, series: list[float] | None = None) -> list[float]:
        series = series or self._c
        k = 2 / (period + 1)
        out: list[float] = []
        prev = series[0] if series else 0.0
        for value in series:
            prev = value * k + prev * (1 - k)
            out.append(prev)
        return out

    def ema(self, period: int, index: int | None = None) -> float:
        series = self.ema_series(period)
        return series[len(series) - 1 if index is None else index]

    def rsi(self, period: int = 14, index: int | None = None) -> float:
        end = len(self._c) if index is None else index + 1
        if end < period + 1:
            return 50.0
        gains = losses = 0.0
        for k in range(end - period, end):
            change = self._c[k] - self._c[k - 1]
            gains += max(change, 0.0)
            losses += max(-change, 0.0)
        if losses == 0:
            return 100.0
        rs = (gains / period) / (losses / period)
        return 100 - 100 / (1 + rs)

    def stdev(self, period: int, index: int | None = None) -> float:
        end = len(self._c) if index is None else index + 1
        window = self._c[max(0, end - period) : end]
        if len(window) < 2:
            return 0.0
        mean = sum(window) / len(window)
        return math.sqrt(sum((v - mean) ** 2 for v in window) / (len(window) - 1))

    def donchian(self, period: int, index: int | None = None) -> tuple[float, float]:
        end = len(self._rows_or_self()) if index is None else index + 1
        highs = self._h[max(0, end - period) : end]
        lows = self._l[max(0, end - period) : end]
        return (max(highs) if highs else 0.0, min(lows) if lows else 0.0)

    def _rows_or_self(self) -> list[dict]:
        return self.rows

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9, index: int | None = None) -> tuple[float, float, float]:
        line = [a - b for a, b in zip(self.ema_series(fast), self.ema_series(slow))]
        sig = self.ema_series(signal, line)
        idx = len(line) - 1 if index is None else index
        return (line[idx], sig[idx], line[idx] - sig[idx])

    def to_points(self, price: float) -> float:
        return price / self.point

    def price_at(self, index: int) -> float:
        return self._c[index]


# --------------------------------------------------------------------------- #
# strategy sandbox
# --------------------------------------------------------------------------- #


class StrategyError(RuntimeError):
    pass


def compile_strategy(source: str) -> tuple[Callable | None, Callable]:
    """Execute the user source and return ``(init_fn, on_bar_fn)``."""
    if not source.strip():
        raise StrategyError("the strategy file is empty")
    try:
        code = compile(source, "<algo>", "exec", flags=0)
    except SyntaxError as exc:
        raise StrategyError(f"syntax error on line {exc.lineno}: {exc.msg}") from exc
    ns: dict[str, Any] = {
        "__name__": "user_algo",
        "__builtins__": SAFE_BUILTINS,
        "math": math,
        "time": time,
        "Bars": Bars,
    }
    try:
        exec(code, ns)  # noqa: S102 - deliberate: user-provided strategy code
    except Exception as exc:  # noqa: BLE001
        raise StrategyError(f"error while loading module: {exc.__class__.__name__}: {exc}") from exc
    on_bar = ns.get("on_bar") or ns.get("on_tick")
    if not callable(on_bar):
        raise StrategyError("the strategy must define on_bar(ctx, bars, i)")
    init_fn = ns.get("init")
    return (init_fn if callable(init_fn) else None), on_bar


_SAFE_NAMES = {
    "abs", "all", "any", "bool", "dict", "float", "int", "len", "list", "max", "min",
    "print", "range", "round", "set", "sorted", "str", "sum", "tuple", "enumerate",
    "zip", "map", "filter", "reversed", "next", "iter", "isinstance", "getattr",
    "setattr", "hasattr", "Exception", "ValueError", "KeyError", "ZeroDivisionError",
    "None", "True", "False", "divmod", "min", "any", "format", "sorted",
}


class _SafeBuiltins(dict):
    """A restricted ``__builtins__`` - no imports, no open, no eval."""

    def __init__(self) -> None:
        import builtins

        super().__init__({k: getattr(builtins, k) for k in _SAFE_NAMES if hasattr(builtins, k)})
        self["__import__"] = _blocked
        self["open"] = _blocked
        self["eval"] = _blocked
        self["exec"] = _blocked
        self["compile"] = _blocked
        self["globals"] = _blocked
        self["locals"] = _blocked
        self["input"] = _blocked
        self["exit"] = _blocked
        self["breakpoint"] = _blocked


def _blocked(*_a, **_k):
    raise StrategyError("that builtin is disabled inside a strategy (sandbox)")


SAFE_BUILTINS = _SafeBuiltins()


class Ctx:
    """The object a strategy receives: config, params, helpers, state."""

    def __init__(self, algo: dict, engine: "AlgoEngine | None" = None) -> None:
        self.symbol = algo["symbol"]
        self.timeframe = algo["timeframe"]
        self.volume = algo.get("volume", 0.01)
        self.stop_loss_points = algo.get("stop_loss_points")
        self.take_profit_points = algo.get("take_profit_points")
        self.trailing_points = algo.get("trailing_points")
        self.risk_percent = algo.get("risk_percent", 1.0)
        self.volume_from_risk = algo.get("volume_from_risk", False)
        self.one_position_per_symbol = algo.get("one_position_per_symbol", True)
        self.allow_reverse = algo.get("allow_reverse", True)
        self.magic = algo.get("magic", 0)
        self.comment = algo.get("comment", "algo")
        self.params = dict(algo.get("params") or {})
        self.p = self.params
        self.ready = 0
        self.index = -1
        self.now = time.time()
        self.balance: float | None = None
        self.equity: float | None = None
        self.position: dict | None = None
        self.position_count = 0
        self.last_price: float | None = None
        self.meta: dict = {}
        self.log = _NullLog()
        self._engine = engine
        self.st = {}  # persistent scratch space owned by the strategy

    def set_params(self, params: dict) -> None:
        self.params.update(params)
        self.p = self.params

    def compute_volume(self, balance: float | None = None) -> float:
        if not self.volume_from_risk:
            return self.volume
        bal = balance if balance is not None else self.balance
        if not bal or not self.stop_loss_points:
            return self.volume
        return broker.estimate_lots(
            float(bal), float(self.risk_percent), float(self.stop_loss_points), self.meta
        )

    @property
    def bars(self) -> Bars | None:
        return self._bars if self._engine else None

    _bars: Bars | None = None

    def has_position(self) -> bool:
        return self.position is not None


class _NullLog:
    def __call__(self, *args: Any, **_k: Any) -> None:
        return None


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #


def list_algos() -> list[dict]:
    out = []
    for rec in data.algos.read()["items"]:
        out.append(public_algo(rec))
    return out


def get_algo(algo_id: str) -> dict | None:
    for rec in data.algos.read()["items"]:
        if rec["id"] == algo_id:
            return rec
    return None


def public_algo(rec: dict) -> dict:
    source = rec.get("source_bytes", 0)
    return {
        "id": rec["id"],
        "name": rec["name"],
        "description": rec.get("description", ""),
        "engine": rec.get("engine", "python"),
        "symbol": rec["symbol"],
        "timeframe": rec["timeframe"],
        "volume": rec.get("volume", 0.01),
        "volume_from_risk": rec.get("volume_from_risk", False),
        "risk_percent": rec.get("risk_percent", 1.0),
        "stop_loss_points": rec.get("stop_loss_points"),
        "take_profit_points": rec.get("take_profit_points"),
        "trailing_points": rec.get("trailing_points"),
        "one_position_per_symbol": rec.get("one_position_per_symbol", True),
        "allow_reverse": rec.get("allow_reverse", True),
        "max_daily_loss_percent": rec.get("max_daily_loss_percent", 0.0),
        "max_open_positions": rec.get("max_open_positions", 1),
        "magic": rec.get("magic"),
        "comment": rec.get("comment", "algo"),
        "params": rec.get("params") or {},
        "account_id": rec.get("account_id"),
        "status": rec.get("status", "stopped"),
        "has_source": bool(source),
        "source_bytes": source or 0,
        "error": rec.get("error"),
        "stats": rec.get("stats") or {},
        "deploy": {k: v for k, v in (rec.get("deploy") or {}).items() if k != "token"},
        "token": rec.get("token"),
        "updated_at": rec.get("updated_at", 0),
    }


def create_algo(payload) -> dict:
    name = payload.name.strip()
    if any(a["name"].lower() == name.lower() for a in data.algos.read()["items"]):
        raise ValueError(f"an algo named '{name}' already exists")
    algo_id = new_id("algo")
    source = payload.source.strip()
    engine = payload.engine
    if engine in ("python", "hybrid") and not source:
        source = starter_source()
    if engine == "mql5" and not source:
        source = ""  # user pastes their own .mq5 source; nothing to scaffold
    token = new_id("tok").replace("tok_", "t") + new_token_suffix()
    rec = {
        "id": algo_id,
        "name": name,
        "description": payload.description,
        "engine": engine,
        "symbol": payload.symbol.upper(),
        "timeframe": payload.timeframe,
        "volume": payload.volume,
        "volume_from_risk": payload.volume_from_risk,
        "risk_percent": payload.risk_percent,
        "stop_loss_points": payload.stop_loss_points,
        "take_profit_points": payload.take_profit_points,
        "trailing_points": payload.trailing_points,
        "one_position_per_symbol": payload.one_position_per_symbol,
        "allow_reverse": payload.allow_reverse,
        "run_on_timer": payload.run_on_timer,
        "max_daily_loss_percent": payload.max_daily_loss_percent,
        "max_open_positions": payload.max_open_positions,
        "magic": payload.magic or (20260917 + abs(hash(algo_id)) % 1000),
        "comment": payload.comment or name[:32],
        "params": payload.params or {},
        "account_id": payload.account_id or _default_account_id(),
        "token": token,
        "status": "stopped",
        "error": None,
        "stats": {},
        "deploy": {},
        "updated_at": now(),
    }
    if source:
        rec["source_bytes"] = data.write_algo_source(algo_id, source)
        if engine == "mql5":
            rec["deploy"]["ea_source"] = str(len(MQL5.generate_ea(rec, source="")))
    data.algos.mutate(lambda store: store["items"].append(rec))
    data.log_audit("algo.create", f"{name} [{engine}] on {rec['symbol']} {rec['timeframe']}")
    return rec


def update_algo(algo_id: str, patch: dict) -> dict:
    def _mutate(store: dict) -> dict | None:
        rec = next((i for i in store["items"] if i["id"] == algo_id), None)
        if rec is None:
            return None
        for key, value in patch.items():
            if value is None:
                continue
            if key == "symbol":
                value = str(value).upper()
            rec[key] = value
        rec["updated_at"] = now()
        return rec

    rec = data.algos.mutate(_mutate)
    if rec is None:
        raise KeyError(algo_id)
    return rec


def set_source(algo_id: str, source: str) -> dict:
    size = data.write_algo_source(algo_id, source)

    def _mutate(store: dict) -> dict | None:
        rec = next((i for i in store["items"] if i["id"] == algo_id), None)
        if rec is None:
            return None
        rec["source_bytes"] = size
        rec["updated_at"] = now()
        rec["error"] = None
        return rec

    rec = data.algos.mutate(_mutate)
    if rec is None:
        raise KeyError(algo_id)
    return rec


def read_source(algo_id: str) -> str:
    return data.read_algo_source(algo_id)


def delete_algo(algo_id: str) -> None:
    engine = _engines.pop(algo_id, None)
    if engine:
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().create_task(engine.stop("deleted"))
    with contextlib.suppress(Exception):
        asyncio.create_task(MQL5.undeploy(get_algo(algo_id) or {"id": algo_id}))

    def _mutate(store: dict) -> None:
        store["items"] = [i for i in store["items"] if i["id"] != algo_id]

    data.algos.mutate(_mutate)
    LOG_FILES.pop(algo_id, None)
    with contextlib.suppress(OSError):
        (data.algo_dir / f"{algo_id}.py").unlink(missing_ok=True)
        (data.algo_dir / f"{algo_id}.mq5").unlink(missing_ok=True)
    data.log_audit("algo.delete", algo_id)


def _default_account_id() -> str | None:
    return data.accounts.read().get("default_account_id")


def new_token_suffix() -> str:
    import secrets

    return secrets.token_hex(10)


# --------------------------------------------------------------------------- #
# logging per algo
# --------------------------------------------------------------------------- #


def append_log(algo_id: str, text: str, level: str = "info") -> None:
    rows = LOG_FILES.setdefault(algo_id, [])
    row = {"ts": time.time(), "level": level, "text": str(text)[:600]}
    rows.append(row)
    if len(rows) > MAX_LOG_ROWS:
        del rows[: len(rows) - MAX_LOG_ROWS]
    hub.agent_logs.publish({"type": "algo_log", "algo": algo_id, **row})


def get_log(algo_id: str, since: float = 0.0, limit: int = 200) -> list[dict]:
    rows = LOG_FILES.get(algo_id, [])
    tail = [r for r in rows if r["ts"] >= since][-limit:]
    return tail


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #


class AlgoEngine:
    def __init__(self, algo: dict) -> None:
        self.algo_id = algo["id"]
        self.name = algo["name"]
        self.status = "stopped"
        self.task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()
        self.bars: Bars | None = None
        self.conn = None
        self.state: dict = {"signals": 0, "orders": 0, "errors": 0}
        self._init_fn: Callable | None = None
        self._bar_fn: Callable | None = None
        self._last_bar_time = 0
        self._day_start_equity: float | None = None
        self._halted_reason: str | None = None
        self._ctx = Ctx(algo, self)
        self._push_task: asyncio.Task | None = None
        self.pending_action: str | None = None
        self.pushed_signal: dict[str, Any] = {"action": "none", "ts": 0.0}
        self._trade_on_replay = False

    # ---- lifecycle ---------------------------------------------------- #
    async def start(self, lookback: int = 600, replay: bool = True, trade_on_replay: bool = False) -> None:
        rec = get_algo(self.algo_id) or {}
        source = read_source(self.algo_id)
        if rec.get("engine") in ("mql5", "hybrid"):
            await self._start_mql5(rec, source)
            return
        self._init_fn, self._bar_fn = compile_strategy(source)
        self.conn = broker.connection(rec.get("account_id"))
        await self.conn.ensure_ready()
        self._ctx = Ctx(rec, self)
        self._ctx.log = lambda *a, **k: append_log(self.algo_id, " ".join(str(x) for x in a))
        meta = await self.conn.gateway.symbol_info(rec["symbol"])
        self._ctx.meta = meta
        self.status = "running"
        self._set(rec, status="running", error=None, stats={**rec.get("stats", {}), "started_at": now()})
        append_log(self.algo_id, f"engine starting on {rec['symbol']} {rec['timeframe']} (lookback {lookback})")
        with contextlib.suppress(Exception):
            await self._ctx.log and None  # no-op guard for strategies without logging
        if self._init_fn:
            try:
                self._init_fn(self._ctx)
            except Exception as exc:  # noqa: BLE001
                append_log(self.algo_id, f"init() raised: {exc}", "error")
        market.add_price_listener(self._on_prices)
        self._ctx.log = lambda *a, **k: append_log(self.algo_id, " ".join(str(x) for x in a))
        self._trade_on_replay = trade_on_replay
        self.task = asyncio.create_task(self._run(rec, lookback, replay), name=f"algo-{self.algo_id}")
        self._set(self.algo_id and rec or rec, status="running")

    async def _start_mql5(self, rec: dict, source: str) -> None:
        """Deploy the Expert Advisor (pure MQL5) or the bridge EA (hybrid)."""
        append_log(self.algo_id, "deploying Expert Advisor through the Bridge agent ...")
        if rec.get("engine") == "hybrid":
            if not source.strip():
                raise GatewayError("hybrid mode needs the python strategy source")
            self._init_fn, self._bar_fn = compile_strategy(source)
            self.conn = broker.connection(rec.get("account_id"))
            await self.conn.ensure_ready()
            self._ctx = Ctx(rec, self)
            self._ctx.meta = await self.conn.gateway.symbol_info(rec["symbol"])
            self._ctx.log = lambda *a, **k: append_log(self.algo_id, " ".join(str(x) for x in a))
            if self._init_fn:
                with contextlib.suppress(Exception):
                    self._init_fn(self._ctx)
            market.add_price_listener(self._on_prices)
            self.status = "running"
            self._set(rec, status="running", error=None)
            self.task = asyncio.create_task(
                self._run_hybrid(rec, settings.HISTORY_BARS), name=f"algo-{self.algo_id}"
            )
            return
        result = await MQL5.deploy(rec, source)
        self.status = "running"
        self._set(rec, status="running", deploy=result.get("deploy", {}), error=None)
        append_log(
            self.algo_id,
            f"EA compiled={result.get('compiled')} file={result.get('ex5_path')} "
            f"chart_attached={result.get('attached', 'via menu')}",
        )
        self._push_task = asyncio.create_task(self._push_signals_loop(rec), name=f"ea-push-{self.algo_id}")

    async def _run_hybrid(self, rec: dict, lookback: int) -> None:
        """Python strategy computes signals; the bridge EA executes them."""
        try:
            await self._warm_history(rec, lookback)
            while not self.stop_event.is_set():
                try:
                    rows = await market.refresh_rates(self.conn.gateway, rec["symbol"], rec["timeframe"], settings.HISTORY_BARS)
                    if rows:
                        self.bars = Bars(rows, rec.get("_meta") or {})
                        self._ctx._bars = self.bars
                        self._ctx.ready = len(rows)
                        index = len(rows) - 1
                        last_time = int(rows[-1]["time"])
                        if last_time != self._last_bar_time:
                            self._last_bar_time = last_time
                            signal = self._evaluate(rows, index)
                            action = (signal or {}).get("action") or "none"
                            if action == "buy":
                                self.pending_action = "buy"
                            elif action == "sell":
                                self.pending_action = "sell"
                            elif action == "close":
                                self.pending_action = "close"
                            else:
                                self.pending_action = None
                            if action in ("buy", "sell", "close"):
                                await self._push_signal_file(rec, action)
                                append_log(self.algo_id, f"signal pushed to EA: {action} ({(signal or {}).get('reason', '')})", "trade")
                                self.state["signals"] = self.state.get("signals", 0) + 1
                        await self._publish_stats(rec)
                except Exception as exc:  # noqa: BLE001
                    self.state["errors"] += 1
                    append_log(self.algo_id, f"hybrid loop: {exc}", "warn")
                await self._sleep_or_stop(3.0)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self.status = "error"
            self._set(rec, status="error", error=f"{exc.__class__.__name__}: {exc}")
        finally:
            market.remove_price_listener(self._on_prices)

    async def _push_signal_file(self, rec: dict, action: str) -> None:
        try:
            await MQL5.push_signal(rec, action, volume=rec.get("volume"), sl_points=rec.get("stop_loss_points"),
                                   tp_points=rec.get("take_profit_points"), kill=bool(self._halted_reason))
            self.pushed_signal = {"action": action, "ts": now()}
            # the signal is a one-shot: reset so the EA does not re-trade it
            self.pending_action = None
            await asyncio.sleep(0.4)
            await MQL5.push_signal(rec, "none", volume=rec.get("volume"), sl_points=rec.get("stop_loss_points"),
                                   tp_points=rec.get("take_profit_points"), kill=bool(self._halted_reason))
        except Exception as exc:  # noqa: BLE001
            append_log(self.algo_id, f"signal file push failed: {exc}", "warn")

    async def _push_signals_loop(self, rec: dict) -> None:
        """Write the signal file into the terminal's MQL5\\Files sandbox."""
        while not self.stop_event.is_set():
            try:
                payload = MQL5.signal_payload(rec)
                conn = broker.connection(rec.get("account_id"))
                await conn.gateway.call(
                    "fs_write",
                    path=MQL5.signal_file_name(rec),
                    content=payload,
                    mode="filesandbox",
                )
                self._set(rec, deploy={**(rec.get("deploy") or {}), "last_push": now()})
            except Exception as exc:  # noqa: BLE001
                append_log(self.algo_id, f"signal push failed: {exc}", "warn")
                await asyncio.sleep(10)
            await asyncio.sleep(5)

    async def stop(self, reason: str = "stopped by user") -> None:
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        if self._push_task:
            self._push_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._push_task
        market.remove_price_listener(self._on_prices)
        self.status = "stopped"
        rec = get_algo(self.algo_id) or {}
        self._set(rec, status="stopped", error=None)
        append_log(self.algo_id, f"engine stopped ({reason})")

    def _set(self, _rec: dict, **fields) -> None:
        def _mutate(store: dict) -> None:
            row = next((i for i in store["items"] if i["id"] == self.algo_id), None)
            if row is None:
                return
            row.update(fields)
            row["updated_at"] = now()

        data.algos.mutate(_mutate)

    # ---- price driven ------------------------------------------------- #
    async def _on_prices(self, changed: dict[str, dict]) -> None:
        rec = get_algo(self.algo_id) or {}
        symbol = rec.get("symbol")
        if not symbol or symbol not in changed:
            return
        self._ctx.last_price = changed[symbol].get("mid") or changed[symbol].get("bid")

    # ---- main loop ---------------------------------------------------- #
    async def _run(self, rec: dict, lookback: int, replay: bool) -> None:
        try:
            await self._warm_history(rec, lookback)
            if replay:
                await self._replay(rec, lookback)
            while not self.stop_event.is_set():
                await self._tick_once(rec)
                await self._sleep_or_stop(2.5)
        except asyncio.CancelledError:  # normal shutdown
            return
        except Exception as exc:  # noqa: BLE001
            self.status = "error"
            message = f"{exc.__class__.__name__}: {exc}"
            log.warning("algo %s crashed: %s", self.name, message)
            append_log(self.algo_id, message, "error")
            self._set(rec, status="error", error=message, traceback=traceback.format_exc(limit=4))
        finally:
            market.remove_price_listener(self._on_prices)

    async def _warm_history(self, rec: dict, lookback: int) -> None:
        rows = await market.refresh_rates(self.conn.gateway, rec["symbol"], rec["timeframe"], lookback)
        if not rows:
            raise GatewayError(f"no candles returned for {rec['symbol']} {rec['timeframe']} yet")
        self.bars = Bars(rows, rec.get("_meta") or {})
        self._ctx._bars = self.bars
        self._ctx.ready = len(rows)

    async def _replay(self, rec: dict, lookback: int) -> None:
        """Fast pass over history so indicator state converges before live.

        Historical signals are *not* traded by default: a strategy that fires on
        bars from an hour ago would open a position right now for no reason.
        Set ``trade_on_replay`` if you deliberately want the warm-up pass to trade.
        """
        assert self.bars is not None
        rows = self.bars.rows
        start = max(0, len(rows) - min(lookback, len(rows)))
        signals = 0
        traded = 0
        for index in range(start, len(rows) - 1):
            signal = self._evaluate(rows, index)
            if signal and signal.get("action") in ("buy", "sell", "close"):
                signals += 1
                if self._trade_on_replay:
                    await self._execute(rec, signal, rows[index])
                    traded += 1
        note = f"{traded} traded during warm-up" if self._trade_on_replay else "warm-up signals were not traded"
        append_log(self.algo_id, f"history primed: {len(rows) - start} bars replayed, {signals} signal(s), {note}")

    async def _tick_once(self, rec: dict) -> None:
        symbol = rec["symbol"]
        rows = await market.refresh_rates(self.conn.gateway, symbol, rec["timeframe"], settings.HISTORY_BARS)
        if not rows:
            return
        self.bars = Bars(rows, rec.get("_meta") or {})
        self._ctx._bars = self.bars
        self._ctx.ready = len(rows)
        self._ctx.index = len(rows) - 1
        self._ctx.now = time.time()

        # account / position sync
        snapshot = await self._sync_state(rec, symbol)
        if snapshot is None:
            return
        # hard risk guard
        if data.config.read().get("kill_switch"):
            if not self._halted_reason:
                self._halted_reason = "kill switch"
                append_log(self.algo_id, "KILL SWITCH engaged - no new orders, engine idling", "warn")
            return
        self._halted_reason = None
        if rec.get("max_daily_loss_percent"):
            day_pnl = (snapshot.get("equity") or 0) - (self._day_start_equity or snapshot.get("equity") or 0)
            limit = -(float(rec["max_daily_loss_percent"]) / 100 * (self._day_start_equity or 0))
            if self._day_start_equity and day_pnl <= limit:
                append_log(self.algo_id, f"daily loss limit hit ({day_pnl:.2f} <= {limit:.2f}) - engine halted", "error")
                self._set(rec, error="daily loss limit reached")
                await self._sleep_or_stop(300)
                return

        last_time = int(rows[-1]["time"])
        fresh_bar = last_time != self._last_bar_time
        if fresh_bar:
            self._last_bar_time = last_time
        # by default a signal is only considered on a newly closed bar; run_on_timer
        # lets intra-bar price movement fire earlier (noisier, but responsive)
        if fresh_bar or rec.get("run_on_timer"):
            signal = self._evaluate(rows, len(rows) - 1)
        else:
            signal = None
        if signal and signal.get("action") in ("buy", "sell", "close"):
            await self._execute(rec, signal, rows[-1])
        await self._manage_exits(rec, rows[-1], fresh_bar)
        await self._publish_stats(rec)

    async def _sync_state(self, rec: dict, symbol: str) -> dict | None:
        try:
            state = await broker.positions_and_orders(rec.get("account_id"))
        except (GatewayError, Exception) as exc:  # noqa: BLE001
            self.state["errors"] += 1
            append_log(self.algo_id, f"state sync failed: {exc}", "warn")
            return None
        magic = int(rec.get("magic") or 0)
        mine = [p for p in state["positions"] if p["magic"] == magic and p["symbol"] == symbol]
        self._ctx.position = mine[0] if mine else None
        self._ctx.position_count = len([p for p in state["positions"] if p["magic"] == magic])
        acct = state["account"] or {}
        self._ctx.balance = acct.get("balance")
        self._ctx.equity = acct.get("equity")
        if self._day_start_equity is None and acct.get("equity"):
            self._day_start_equity = float(acct["equity"])
        self.state["equity"] = acct.get("equity")
        self.state["balance"] = acct.get("balance")
        self.state["positions"] = self._ctx.position_count
        self.state["floating"] = round(sum(p["profit"] for p in mine), 2)
        return acct

    def _evaluate(self, rows: list[dict], index: int) -> dict | None:
        if self._bar_fn is None or self.bars is None:
            return None
        try:
            result = self._bar_fn(self._ctx, self.bars, index)
        except Exception as exc:  # noqa: BLE001
            self.state["errors"] += 1
            append_log(self.algo_id, f"on_bar() raised: {exc.__class__.__name__}: {exc}", "error")
            return None
        return _normalise_signal(result)

    async def _execute(self, rec: dict, signal: dict, bar: dict) -> None:
        action = signal.get("action")
        assert self.bars is not None
        symbol = rec["symbol"]
        point = float(self.bars.point)
        digits = int(self.bars.digits)
        if action == "close":
            if self._ctx.position is None:
                return
            await broker.close_position(self._ctx.position["ticket"], account_id=rec.get("account_id"))
            append_log(self.algo_id, f"closed position {self._ctx.position['ticket']} ({signal.get('reason', 'flat signal')})", "trade")
            self.state["closes"] = self.state.get("closes", 0) + 1
            return

        if self._ctx.position is not None:
            same_dir = self._ctx.position["type"] == action
            if same_dir and rec.get("one_position_per_symbol", True):
                return
            if not same_dir and rec.get("allow_reverse", True):
                await broker.close_position(self._ctx.position["ticket"], account_id=rec.get("account_id"))
                append_log(self.algo_id, f"reversing: closed {self._ctx.position['ticket']} before {action.upper()}", "trade")
            elif not same_dir:
                return

        if self._ctx.position_count >= int(rec.get("max_open_positions", 1)):
            append_log(self.algo_id, "max open positions reached - signal skipped", "warn")
            return

        # use the freshest price we have: a signal produced during the history
        # warm-up (or a stale cache) must not anchor SL/TP to an old close
        price = float(bar["close"])
        live = market.prices.get(symbol) or {}
        best = float(live.get("ask") or 0) if action == "buy" else float(live.get("bid") or 0)
        if best > 0:
            price = best
        bar_age = time.time() - float(bar.get("time") or 0)
        if bar_age > 120:
            append_log(self.algo_id, f"note: signal bar is {bar_age / 60:.1f} min old, executing at market price {price}", "warn")
        sl_points = rec.get("stop_loss_points")
        tp_points = rec.get("take_profit_points")
        sl = round(price - sl_points * point, digits) if (sl_points and action == "buy") else (
            round(price + sl_points * point, digits) if sl_points else 0.0
        )
        tp = round(price + tp_points * point, digits) if (tp_points and action == "buy") else (
            round(price - tp_points * point, digits) if tp_points else 0.0
        )
        volume = round_to_step(float(signal.get("volume") or self._ctx.compute_volume() or rec.get("volume", 0.01)))
        payload = _OrderRequest(
            symbol=symbol,
            direction=action,
            volume=volume,
            order_type="market",
            price=None,
            stop_loss=sl or None,
            take_profit=tp or None,
            deviation=int(signal.get("deviation", 20)),
            comment=str(signal.get("comment") or rec.get("comment") or self.name)[:32],
            magic=int(rec.get("magic") or 0),
            account_id=rec.get("account_id"),
            sl_points=None,
            tp_points=None,
        )
        try:
            result = await broker.submit_order(payload)
        except GatewayError as exc:
            self.state["errors"] += 1
            append_log(self.algo_id, f"order rejected: {exc}", "error")
            return
        self.state["orders"] += 1
        self.state["signals"] = self.state.get("signals", 0) + 1
        append_log(
            self.algo_id,
            f"{action.upper()} {result['volume']} {symbol} @ {result['price']} "
            f"SL={result['sl'] or '-'} TP={result['tp'] or '-'} order={result['order']} "
            f"({signal.get('reason', 'signal')})",
            "trade",
        )

    async def _manage_exits(self, rec: dict, bar: dict, fresh_bar: bool) -> None:
        """Server-side trailing stop / break-even, evaluated on every close."""
        trailing = rec.get("trailing_points")
        position = self._ctx.position
        if not trailing or not position or self.bars is None:
            return
        point = float(self.bars.point)
        digits = int(self.bars.digits)
        price = float(bar["close"])
        desired = None
        if position["type"] == "buy":
            candidate = round(price - trailing * point, digits)
            if candidate > position["sl"] + point / 2:
                desired = candidate
        else:
            candidate = round(price + trailing * point, digits)
            if not position["sl"] or candidate < position["sl"] - point / 2:
                desired = candidate
        if desired is not None:
            with contextlib.suppress(GatewayError):
                await broker.modify_position(position["ticket"], desired, position["tp"] or None, account_id=rec.get("account_id"))
                append_log(self.algo_id, f"trailing stop -> {desired}", "trade")

    async def _publish_stats(self, rec: dict) -> None:
        stats = {
            **self.state,
            "symbol": rec["symbol"],
            "timeframe": rec["timeframe"],
            "price": (self.bars.close[-1] if self.bars else None),
            "bars": (len(self.bars) if self.bars else 0),
            "last_bar": self._last_bar_time,
            "heartbeat": now(),
            "status": self.status,
        }
        self._set(rec, stats=stats)
        hub.trade_events.publish({"ts": now(), "type": "algo", "algo": self.algo_id, "name": self.name, **stats})

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass


def _normalise_signal(result: Any) -> dict | None:
    if result is None:
        return None
    if isinstance(result, (int, float)):
        return {1: {"action": "buy"}, -1: {"action": "sell"}, 0: {"action": "close"}}.get(int(result))
    if isinstance(result, str):
        value = result.strip().lower()
        if value in ("buy", "sell", "close"):
            return {"action": value}
        return None
    if isinstance(result, dict) and result.get("action"):
        action = str(result["action"]).lower()
        if action in ("long",):
            result = {**result, "action": "buy"}
        elif action in ("short",):
            result = {**result, "action": "sell"}
        elif action in ("flat", "exit", "none"):
            result = {**result, "action": "close"}
        if str(result.get("action")).lower() in ("buy", "sell", "close"):
            return result
    return None


class _OrderRequest:
    """Duck-typed stand-in for models.OrderRequest used by the engine."""

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


# --------------------------------------------------------------------------- #
# registry / API surface
# --------------------------------------------------------------------------- #

_engines: dict[str, AlgoEngine] = {}


def engine(algo_id: str) -> AlgoEngine | None:
    return _engines.get(algo_id)


async def start_algo(algo_id: str, lookback: int = 600, replay: bool = True, trade_on_replay: bool = False) -> dict:
    rec = get_algo(algo_id)
    if rec is None:
        raise KeyError(algo_id)
    existing = _engines.get(algo_id)
    if existing:
        await existing.stop("restart")
    eng = AlgoEngine(rec)
    _engines[algo_id] = eng
    await eng.start(lookback=lookback, replay=replay, trade_on_replay=trade_on_replay)
    data.log_audit("algo.start", rec["name"])
    return public_algo(get_algo(algo_id) or rec)


async def stop_algo(algo_id: str, reason: str = "stopped") -> dict:
    rec = get_algo(algo_id)
    eng = _engines.pop(algo_id, None)
    if eng:
        await eng.stop(reason)
    elif rec:
        def _mutate(store: dict) -> None:
            row = next((i for i in store["items"] if i["id"] == algo_id), None)
            if row:
                row["status"] = "stopped"
                row["updated_at"] = now()

        data.algos.mutate(_mutate)
    if rec and rec.get("engine") == "mql5":
        with contextlib.suppress(Exception):
            await MQL5.undeploy(rec)
    data.log_audit("algo.stop", (rec or {}).get("name", algo_id))
    return public_algo(get_algo(algo_id) or rec or {"id": algo_id})


async def stop_all(reason: str = "app shutdown") -> None:
    for algo_id in list(_engines):
        with contextlib.suppress(Exception):
            await stop_algo(algo_id, reason)


async def preview(payload) -> dict:
    """Backtest the given source against real candles from the terminal."""
    conn = broker.connection()
    await conn.ensure_ready()
    rows = await conn.gateway.rates(payload.symbol, payload.timeframe, payload.bars)
    if not rows:
        raise GatewayError(f"no candles for {payload.symbol} yet - is the terminal connected?")
    init_fn, bar_fn = compile_strategy(payload.source)
    fake = {
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "volume": payload.volume,
        "stop_loss_points": payload.stop_loss_points,
        "take_profit_points": payload.take_profit_points,
        "trailing_points": None,
        "risk_percent": 1.0,
        "volume_from_risk": False,
        "magic": 0,
        "comment": "preview",
        "params": payload.params or {},
    }
    ctx = Ctx(fake)
    logs: list[str] = []
    ctx.log = lambda *a, **k: logs.append(" ".join(str(x) for x in a))
    if init_fn:
        init_fn(ctx)

    def evaluate(rows_slice: list[dict], index: int) -> dict | None:
        bars = Bars(rows_slice, {})
        ctx.ready = len(rows_slice)
        ctx.index = index
        return _normalise_signal(bar_fn(ctx, bars, index))

    result = run_backtest(
        evaluate,
        rows,
        volume=payload.volume,
        stop_loss_points=payload.stop_loss_points,
        take_profit_points=payload.take_profit_points,
        meta={},
    )
    result["logs"] = logs[-25:]
    return result


async def backtest_algo(algo_id: str, bars: int = 800) -> dict:
    rec = get_algo(algo_id)
    if rec is None:
        raise KeyError(algo_id)

    class _Payload:
        pass

    p = _Payload()
    p.source = read_source(algo_id)
    p.symbol = rec["symbol"]
    p.timeframe = rec["timeframe"]
    p.bars = bars
    p.volume = rec.get("volume", 0.01)
    p.stop_loss_points = rec.get("stop_loss_points")
    p.take_profit_points = rec.get("take_profit_points")
    p.params = rec.get("params") or {}
    result = await preview(p)
    append_log(algo_id, f"backtest: {result['trade_count']} trades, net {result['net_money']} "
                        f"({result['net_points']} pts), win rate {result['win_rate']}%")
    return result


# --------------------------------------------------------------------------- #
# starter code shown in Algo Studio
# --------------------------------------------------------------------------- #

STARTERS: dict[str, str] = {}


def starter_source(kind: str = "ema") -> str:
    return STARTERS.get(kind) or STARTERS["ema"]


def register_starter(name: str, source: str) -> None:
    STARTERS[name] = source


register_starter(
    "ema",
    '''# EMA cross + RSI filter  -  edit freely, then press Run
# ctx.p holds user parameters (also editable in the Params tab)

def init(ctx):
    ctx.p.setdefault("fast", 12)
    ctx.p.setdefault("slow", 26)
    ctx.p.setdefault("rsi_period", 14)
    ctx.p.setdefault("rsi_buy_max", 68.0)
    ctx.p.setdefault("rsi_sell_min", 32.0)
    ctx.log(f"starting on {ctx.symbol} {ctx.timeframe}, fast={ctx.p['fast']} slow={ctx.p['slow']}")


def on_bar(ctx, bars, i):
    if i < ctx.p["slow"] + 2:
        return None

    fast = bars.ema(ctx.p["fast"], i)
    slow = bars.ema(ctx.p["slow"], i)
    fast_prev = bars.ema(ctx.p["fast"], i - 1)
    slow_prev = bars.ema(ctx.p["slow"], i - 1)
    rsi = bars.rsi(ctx.p["rsi_period"], i)

    cross_up = fast_prev <= slow_prev and fast > slow
    cross_down = fast_prev >= slow_prev and fast < slow

    if cross_up and rsi < ctx.p["rsi_buy_max"]:
        return {"action": "buy", "volume": ctx.volume, "reason": f"EMA cross up, rsi {rsi:.0f}"}
    if cross_down and rsi > ctx.p["rsi_sell_min"]:
        return {"action": "sell", "volume": ctx.volume, "reason": f"EMA cross down, rsi {rsi:.0f}"}
    return None
''',
)

register_starter(
    "donchian",
    '''# Donchian breakout with ATR-based stops

def init(ctx):
    ctx.p.setdefault("channel", 20)
    ctx.p.setdefault("exit_channel", 10)


def on_bar(ctx, bars, i):
    if i < ctx.p["channel"] + 2:
        return None
    hi, _ = bars.donchian(ctx.p["channel"], i - 1)
    _, lo = bars.donchian(ctx.p["exit_channel"], i - 1)
    atr = bars.atr_points(i - 1, 14)

    price = bars.close[i]
    if price > hi and not ctx.has_position():
        return {"action": "buy", "reason": f"breakout above {hi:.5f} (atr {atr:.0f} pts)"}
    if ctx.position and ctx.position["type"] == "buy" and price < lo:
        return {"action": "close", "reason": "channel exit"}
    return None
''',
)

register_starter(
    "grid",
    '''# Simple mean-reversion grid (careful: real money, real drawdown)

def init(ctx):
    ctx.p.setdefault("period", 50)
    ctx.p.setdefault("band_sigma", 2.0)


def on_bar(ctx, bars, i):
    if i < ctx.p["period"] + 1:
        return None
    mean = bars.sma(ctx.p["period"], i)
    sigma = bars.stdev(ctx.p["period"], i) or 1e-9
    z = (bars.close[i] - mean) / sigma
    if z < -ctx.p["band_sigma"]:
        return {"action": "buy", "reason": f"oversold z={z:.2f}"}
    if z > ctx.p["band_sigma"]:
        return {"action": "sell", "reason": f"overbought z={z:.2f}"}
    if abs(z) < 0.4 and ctx.has_position():
        return {"action": "close", "reason": f"mean reached z={z:.2f}"}
    return None
''',
)
